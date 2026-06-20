"""
GPU Backend Model: simulates H100 and L4 behavior.

Models:
- HBM memory constraints
- Prefill computation (memory-bound, processes prefix, outputs KV cache)
- Decode generation (compute-bound, 1 token per step per request)
- Block pinning/unpinning during operations
- LRU eviction when HBM full
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import heapq


@dataclass
class DecodeRequest:
    """A request in decode phase."""

    request_id: str
    tokens_generated: int = 0
    target_tokens: int = 0  # How many tokens to generate

    def is_complete(self) -> bool:
        return self.tokens_generated >= self.target_tokens


@dataclass
class PrefillOperation:
    """A prefill operation in progress."""

    operation_id: str
    request_id: str
    block_id: str  # Block being prefilled
    prefill_complete_time: float  # When prefill finishes (ms)
    kv_cache_bytes: int  # Size of KV cache output


@dataclass
class GPUInstanceConfig:
    """Configuration for a GPU instance."""

    instance_id: str
    model_id: str  # 'Llama-405B', 'Llama-8B', etc.
    hbm_capacity_bytes: int  # Total HBM bytes
    prefill_throughput_tokens_per_sec: float  # Tokens prefilled per second (entire batch)
    decode_latency_per_token_ms: float  # Latency per token during decode (single token generation)
    max_batch_size: int = 256  # Max requests in decode batch


class GPUInstance:
    """Simulates a single GPU instance."""

    def __init__(self, config: GPUInstanceConfig):
        self.config = config
        self.instance_id = config.instance_id
        self.model_id = config.model_id

        # HBM state
        self.hbm_used_bytes = 0
        self.hbm_capacity_bytes = config.hbm_capacity_bytes

        # Block management
        self.blocks: Dict[str, "BlockState"] = {}  # block_id → BlockState

        # Request queues
        self.prefill_queue: List[Tuple[float, int, PrefillOperation]] = []  # Min-heap by (complete_time, sequence, op)
        self.decode_requests: Dict[str, DecodeRequest] = {}  # request_id → DecodeRequest

        # Telemetry
        self.epoch = 0  # Incremented on each reboot
        self.operations_completed = 0
        self.operation_sequence = 0  # For unique heap ordering

    @dataclass
    class BlockState:
        """State of a cached KV block on this instance."""

        block_id: str
        kv_cache_bytes: int
        pin_count: int = 0
        lru_timestamp: float = 0.0

        def is_evictable(self) -> bool:
            return self.pin_count == 0

    def get_hbm_free(self) -> int:
        """Free HBM available."""
        return self.hbm_capacity_bytes - self.hbm_used_bytes

    def has_block(self, block_id: str) -> bool:
        """Check if block is cached."""
        return block_id in self.blocks

    def add_block(
        self, block_id: str, kv_cache_bytes: int, current_time: float
    ) -> bool:
        """
        Add a block to this instance.

        Evicts LRU blocks if necessary to make space.

        Args:
            block_id: Block identifier
            kv_cache_bytes: Size of KV cache
            current_time: Current simulation time (for LRU timestamp)

        Returns:
            True if block added successfully, False if unable to fit (even after eviction).
        """
        # Evict LRU blocks until we have space
        while self.get_hbm_free() < kv_cache_bytes:
            evicted = self._evict_lru()
            if evicted is None:
                # No evictable blocks available
                return False

        # Add block
        self.blocks[block_id] = self.BlockState(
            block_id=block_id,
            kv_cache_bytes=kv_cache_bytes,
            pin_count=0,
            lru_timestamp=current_time,
        )
        self.hbm_used_bytes += kv_cache_bytes
        return True

    def _evict_lru(self) -> Optional[str]:
        """
        Evict the least-recently-used evictable block.

        Returns:
            block_id of evicted block, or None if no evictable blocks.
        """
        evictable = [
            (b.lru_timestamp, bid) for bid, b in self.blocks.items() if b.is_evictable()
        ]
        if not evictable:
            return None

        # Evict oldest
        _, block_id = min(evictable)
        block = self.blocks.pop(block_id)
        self.hbm_used_bytes -= block.kv_cache_bytes
        return block_id

    def evict_block(self, block_id: str) -> bool:
        """
        Explicitly evict a block (when state machine says it's gone).

        Args:
            block_id: Block to evict

        Returns:
            True if evicted, False if block doesn't exist or is pinned.
        """
        if block_id not in self.blocks:
            return False

        block = self.blocks[block_id]
        if not block.is_evictable():
            return False

        self.blocks.pop(block_id)
        self.hbm_used_bytes -= block.kv_cache_bytes
        return True

    def pin_block(self, block_id: str) -> None:
        """Increment pin_count (block in use)."""
        if block_id in self.blocks:
            self.blocks[block_id].pin_count += 1

    def unpin_block(self, block_id: str) -> None:
        """Decrement pin_count (block no longer in use)."""
        if block_id in self.blocks:
            self.blocks[block_id].pin_count = max(
                0, self.blocks[block_id].pin_count - 1
            )

    def touch_block(self, block_id: str, current_time: float) -> None:
        """Update LRU timestamp (block accessed)."""
        if block_id in self.blocks:
            self.blocks[block_id].lru_timestamp = current_time

    def schedule_prefill(
        self,
        operation_id: str,
        request_id: str,
        block_id: str,
        num_tokens: int,
        kv_cache_bytes: int,
        current_time: float,
    ) -> None:
        """
        Schedule a prefill operation.

        Args:
            operation_id: Unique ID for this prefill
            request_id: Request being prefilled
            block_id: Block to create/cache
            num_tokens: Number of tokens in prefix
            kv_cache_bytes: Size of output KV cache
            current_time: Current simulation time (ms)
        """
        # Estimate prefill time (memory-bound: throughput limited)
        # Convert tokens/sec to tokens/ms, then compute time
        prefill_throughput_tokens_per_ms = self.config.prefill_throughput_tokens_per_sec / 1000.0
        prefill_time_ms = num_tokens / prefill_throughput_tokens_per_ms
        complete_time = current_time + prefill_time_ms

        op = PrefillOperation(
            operation_id=operation_id,
            request_id=request_id,
            block_id=block_id,
            prefill_complete_time=complete_time,
            kv_cache_bytes=kv_cache_bytes,
        )
        self.operation_sequence += 1
        heapq.heappush(self.prefill_queue, (complete_time, self.operation_sequence, op))

    def step(self, current_time: float) -> List[Tuple[str, str, str]]:
        """
        Execute one simulation step.

        Args:
            current_time: Current simulation time

        Returns:
            List of (event_type, request_id, block_id) events:
            - ('prefill_complete', request_id, block_id)
            - ('decode_complete', request_id, '')
        """
        events = []

        # Process completed prefills
        while self.prefill_queue and self.prefill_queue[0][0] <= current_time:
            _, _, op = heapq.heappop(self.prefill_queue)

            # Add block to HBM
            if self.add_block(op.block_id, op.kv_cache_bytes, current_time):
                events.append(("prefill_complete", op.request_id, op.block_id))
                self.operations_completed += 1
            else:
                # Could not fit block (emergency: instance is over-subscribed)
                # For now, log but don't fail
                pass

        # Advance decode (1 token per request per step)
        completed_requests = []
        for request_id, req in self.decode_requests.items():
            req.tokens_generated += 1
            if req.is_complete():
                completed_requests.append(request_id)

        for request_id in completed_requests:
            del self.decode_requests[request_id]
            events.append(("decode_complete", request_id, ""))
            self.operations_completed += 1

        return events

    def start_decode(self, request_id: str, target_tokens: int) -> None:
        """Start decoding a request."""
        self.decode_requests[request_id] = DecodeRequest(
            request_id=request_id,
            tokens_generated=0,
            target_tokens=target_tokens,
        )

    def get_state_hash(self) -> str:
        """
        Compute state hash for reconciliation.

        Simple hash of all block IDs and pin counts.
        """
        block_info = sorted(
            [(bid, b.pin_count) for bid, b in self.blocks.items()]
        )
        return str(hash(tuple(block_info)))

    def get_telemetry(self) -> Dict:
        """Return telemetry snapshot."""
        return {
            "instance_id": self.instance_id,
            "epoch": self.epoch,
            "hbm_used_bytes": self.hbm_used_bytes,
            "hbm_free_bytes": self.get_hbm_free(),
            "hbm_utilization": self.hbm_used_bytes / self.hbm_capacity_bytes,
            "num_blocks": len(self.blocks),
            "num_pinned_blocks": sum(
                1 for b in self.blocks.values() if b.pin_count > 0
            ),
            "num_decode_requests": len(self.decode_requests),
            "operations_completed": self.operations_completed,
            "state_hash": self.get_state_hash(),
        }
