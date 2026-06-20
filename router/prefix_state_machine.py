"""
Prefix State Machine: tracks KV cache blocks across GPU instances.

Core abstractions:
- Block: a cached KV block with ref counting and LRU metadata
- Prefix chain: hierarchical hashes [h1, h2, h3, ...] where each hash depends on previous
- Query: find longest cached prefix chain
- Eviction: remove blocks with pin_count == 0
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import time


@dataclass
class TransferState:
    """Represents a P2P KV block transfer between GPU instances."""

    transfer_id: str
    block_id: str
    source_instance: str
    target_instance: str
    kv_cache_bytes: int
    start_time: float
    estimated_complete_time: float
    status: str = "pending"  # "pending" | "complete" | "failed"
    failure_reason: Optional[str] = None


@dataclass
class Block:
    """Represents a cached KV block on a GPU instance."""

    block_id: str
    instance_id: str
    parent_hash: Optional[str]  # hash of previous block in chain (None for root)
    own_hash: str  # hash(parent_hash + content); identifies position in chain
    pin_count: int = 0  # ref count; unpinned (0) blocks are evictable
    lru_timestamp: float = field(default_factory=time.time)
    prefix_tokens: int = 0  # tokens in this block
    kv_cache_bytes: int = 0  # KV cache size
    model_id: str = ""  # e.g. 'H100-405B', 'L4-8B'
    epoch: int = 0  # instance epoch when block was created

    def is_evictable(self) -> bool:
        """Block is evictable iff pin_count == 0."""
        return self.pin_count == 0

    def touch(self) -> None:
        """Update LRU timestamp (call on cache hit or pin increment)."""
        self.lru_timestamp = time.time()

    def increment_pin(self) -> None:
        """Increment ref count (request starting to use this block)."""
        self.pin_count += 1
        self.touch()

    def decrement_pin(self) -> None:
        """Decrement ref count (request finished with this block)."""
        self.pin_count = max(0, self.pin_count - 1)


class PrefixStateMachine:
    """
    Tracks cached prefix blocks across GPU fleet.

    Supports:
    - Hierarchical prefix chains (partial cache hits)
    - Reference counting with pinning semantics
    - LRU eviction tracking
    - Per-instance epoch + state-hash tracking for resilience
    """

    def __init__(self):
        self.blocks: Dict[str, Block] = {}  # block_id → Block
        self.chains: Dict[str, str] = {}  # chain_hash → block_id (fast lookup)
        self.instance_epochs: Dict[str, int] = {}  # instance_id → latest epoch
        self.instance_state_hashes: Dict[str, str] = {}  # instance_id → state hash
        self.transfers: Dict[str, TransferState] = {}  # transfer_id → TransferState

    def add_block(self, block: Block) -> None:
        """
        Register a newly cached block (called when GPU prefill completes).

        Args:
            block: Block with block_id, instance_id, parent_hash, own_hash, etc.

        Raises:
            ValueError: if block_id already exists.
        """
        if block.block_id in self.blocks:
            raise ValueError(f"Block {block.block_id} already exists")
        self.blocks[block.block_id] = block
        self.chains[block.own_hash] = block.block_id
        block.touch()

    def increment_pin_count(self, block_id: str) -> None:
        """Increment pin_count (request using this block)."""
        if block_id in self.blocks:
            self.blocks[block_id].increment_pin()

    def decrement_pin_count(self, block_id: str) -> None:
        """Decrement pin_count (request finished with this block)."""
        if block_id in self.blocks:
            self.blocks[block_id].decrement_pin()

    def query_prefix_chain(self, prefix_hashes: List[str]) -> Optional[str]:
        """
        Query: find longest cached prefix chain.

        Args:
            prefix_hashes: [h1, h2, h3, ...] where h_i depends on h_{i-1}.

        Returns:
            block_id of deepest cached block in chain, or None if nothing cached.

        Example:
            prefix_hashes = [hash(system_prompt), hash(hash(system_prompt) + retrieval_context)]
            If h2 is cached, returns its block_id (we can reuse system_prompt KV).
            If only h1 is cached, returns its block_id (we can reuse just system_prompt KV).
        """
        for i in range(len(prefix_hashes) - 1, -1, -1):
            if prefix_hashes[i] in self.chains:
                return self.chains[prefix_hashes[i]]
        return None

    def get_block(self, block_id: str) -> Optional[Block]:
        """Get block by ID."""
        return self.blocks.get(block_id)

    def evict_block(self, block_id: str) -> None:
        """
        Evict a block (called when GPU instance needs HBM space).

        Args:
            block_id: Block to evict.

        Raises:
            RuntimeError: if block is still pinned (pin_count > 0).
        """
        if block_id not in self.blocks:
            return
        block = self.blocks[block_id]
        if not block.is_evictable():
            raise RuntimeError(
                f"Cannot evict pinned block {block_id} (pin_count={block.pin_count})"
            )
        del self.blocks[block_id]
        del self.chains[block.own_hash]

    def force_evict_block(self, block_id: str) -> None:
        """Force evict a block regardless of pin_count (for reboot recovery)."""
        if block_id in self.blocks:
            block = self.blocks[block_id]
            del self.blocks[block_id]
            del self.chains[block.own_hash]

    def update_instance_state(
        self, instance_id: str, epoch: int, state_hash: str
    ) -> None:
        """
        Update instance heartbeat (epoch + state hash).

        Called periodically from GPU instance telemetry.
        """
        self.instance_epochs[instance_id] = epoch
        self.instance_state_hashes[instance_id] = state_hash

    def detect_reboot(self, instance_id: str, new_epoch: int) -> bool:
        """
        Detect if instance rebooted (epoch went backward or reset).

        Returns:
            True if reboot detected.
        """
        old_epoch = self.instance_epochs.get(instance_id, new_epoch)
        return new_epoch < old_epoch

    def clear_instance_blocks(self, instance_id: str) -> None:
        """
        Clear all blocks for an instance (call after reboot detection).

        This is necessary because the instance lost all HBM state.
        """
        to_remove = [
            bid for bid, block in self.blocks.items()
            if block.instance_id == instance_id
        ]
        for block_id in to_remove:
            self.force_evict_block(block_id)

    def reconcile_instance_state(
        self, instance_id: str, remote_blocks: Dict[str, Dict]
    ) -> Tuple[List[str], List[str]]:
        """
        Reconcile state machine vs. actual instance state (from heartbeat).

        Called periodically to heal desyncs from dropped packets.

        Args:
            instance_id: The GPU instance.
            remote_blocks: Dict of {block_id: {block_info}} from instance.

        Returns:
            (to_remove, to_add): Lists of block_ids to remove/add locally.
        """
        local_block_ids = {
            bid for bid, block in self.blocks.items()
            if block.instance_id == instance_id
        }
        remote_block_ids = set(remote_blocks.keys())

        to_remove = list(local_block_ids - remote_block_ids)
        to_add = list(remote_block_ids - local_block_ids)

        # Remove blocks that instance says are gone
        for block_id in to_remove:
            self.force_evict_block(block_id)

        return to_remove, to_add

    def get_instance_blocks(self, instance_id: str) -> List[Block]:
        """Get all blocks on a given instance."""
        return [b for b in self.blocks.values() if b.instance_id == instance_id]

    def initiate_transfer(
        self,
        transfer_id: str,
        block_id: str,
        source_instance: str,
        target_instance: str,
        kv_cache_bytes: int,
        start_time: float,
        estimated_complete_time: float,
    ) -> TransferState:
        """
        Record a P2P KV block transfer request.

        Args:
            transfer_id: Unique transfer identifier
            block_id: Block being transferred
            source_instance: GPU sending the block
            target_instance: GPU receiving the block
            kv_cache_bytes: Size of KV cache to transfer
            start_time: Simulation time when transfer starts
            estimated_complete_time: Estimated time when transfer completes

        Returns:
            TransferState for tracking
        """
        transfer = TransferState(
            transfer_id=transfer_id,
            block_id=block_id,
            source_instance=source_instance,
            target_instance=target_instance,
            kv_cache_bytes=kv_cache_bytes,
            start_time=start_time,
            estimated_complete_time=estimated_complete_time,
            status="pending",
        )
        self.transfers[transfer_id] = transfer
        return transfer

    def complete_transfer(self, transfer_id: str) -> Optional[TransferState]:
        """Mark a transfer as complete."""
        if transfer_id in self.transfers:
            self.transfers[transfer_id].status = "complete"
            return self.transfers[transfer_id]
        return None

    def fail_transfer(self, transfer_id: str, reason: str) -> Optional[TransferState]:
        """Mark a transfer as failed."""
        if transfer_id in self.transfers:
            self.transfers[transfer_id].status = "failed"
            self.transfers[transfer_id].failure_reason = reason
            return self.transfers[transfer_id]
        return None

    def get_transfers_in_flight(self) -> List[TransferState]:
        """Get all pending transfers."""
        return [t for t in self.transfers.values() if t.status == "pending"]

    def get_stats(self) -> Dict:
        """Return current state machine metrics."""
        blocks = list(self.blocks.values())
        transfers = list(self.transfers.values())
        return {
            "num_blocks": len(blocks),
            "pinned_blocks": sum(1 for b in blocks if b.pin_count > 0),
            "evictable_blocks": sum(1 for b in blocks if b.is_evictable()),
            "total_kv_cache_bytes": sum(b.kv_cache_bytes for b in blocks),
            "total_pin_count": sum(b.pin_count for b in blocks),
            "num_instances": len(self.instance_epochs),
            "transfers_pending": sum(1 for t in transfers if t.status == "pending"),
            "transfers_completed": sum(1 for t in transfers if t.status == "complete"),
            "transfers_failed": sum(1 for t in transfers if t.status == "failed"),
        }
