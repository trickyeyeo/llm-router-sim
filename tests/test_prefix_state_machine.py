"""
Unit tests for PrefixStateMachine.
"""

import pytest
import time
from router.prefix_state_machine import Block, PrefixStateMachine


class TestBlockSemantics:
    """Test Block data structure and pin counting."""

    def test_block_creation(self):
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash="h0",
            own_hash="h1",
            prefix_tokens=512,
            kv_cache_bytes=1024 * 1024,  # 1MB
            model_id="H100-405B",
            epoch=1,
        )
        assert block.pin_count == 0
        assert block.is_evictable() is True

    def test_pin_increment_decrement(self):
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
        )
        assert block.pin_count == 0
        assert block.is_evictable() is True

        block.increment_pin()
        assert block.pin_count == 1
        assert block.is_evictable() is False

        block.increment_pin()
        assert block.pin_count == 2
        assert block.is_evictable() is False

        block.decrement_pin()
        assert block.pin_count == 1
        assert block.is_evictable() is False

        block.decrement_pin()
        assert block.pin_count == 0
        assert block.is_evictable() is True

    def test_pin_count_never_negative(self):
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
        )
        block.decrement_pin()
        block.decrement_pin()
        assert block.pin_count == 0

    def test_lru_timestamp_updated_on_touch(self):
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
        )
        t1 = block.lru_timestamp
        time.sleep(0.01)
        block.touch()
        t2 = block.lru_timestamp
        assert t2 > t1


class TestPrefixStateMachineBasics:
    """Test basic state machine operations."""

    def test_add_and_query_single_block(self):
        sm = PrefixStateMachine()
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
            prefix_tokens=512,
            kv_cache_bytes=1024,
        )
        sm.add_block(block)

        # Query with single hash
        result = sm.query_prefix_chain(["h1"])
        assert result == "b1"

        # Query with hash not in cache
        result = sm.query_prefix_chain(["h_unknown"])
        assert result is None

    def test_add_duplicate_block_raises(self):
        sm = PrefixStateMachine()
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
        )
        sm.add_block(block)
        with pytest.raises(ValueError):
            sm.add_block(block)

    def test_get_block(self):
        sm = PrefixStateMachine()
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
        )
        sm.add_block(block)
        retrieved = sm.get_block("b1")
        assert retrieved is not None
        assert retrieved.block_id == "b1"

        assert sm.get_block("b_unknown") is None


class TestHierarchicalPrefixes:
    """Test hierarchical prefix chains (radix-chained hashing)."""

    def test_hierarchical_prefix_chain_full_hit(self):
        """All blocks in chain are cached."""
        sm = PrefixStateMachine()

        # Build chain: system_prompt → system_prompt + retrieval → system_prompt + retrieval + user_turn
        block1 = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h_sys",
            prefix_tokens=512,
            kv_cache_bytes=1024,
        )
        block2 = Block(
            block_id="b2",
            instance_id="gpu0",
            parent_hash="h_sys",
            own_hash="h_sys_ret",
            prefix_tokens=2048,
            kv_cache_bytes=4096,
        )
        block3 = Block(
            block_id="b3",
            instance_id="gpu0",
            parent_hash="h_sys_ret",
            own_hash="h_sys_ret_user",
            prefix_tokens=2560,
            kv_cache_bytes=5120,
        )
        sm.add_block(block1)
        sm.add_block(block2)
        sm.add_block(block3)

        # Query full chain
        result = sm.query_prefix_chain(["h_sys", "h_sys_ret", "h_sys_ret_user"])
        assert result == "b3"  # Deepest (full) hit

    def test_hierarchical_prefix_chain_partial_hit(self):
        """Only first blocks in chain are cached."""
        sm = PrefixStateMachine()

        block1 = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h_sys",
        )
        block2 = Block(
            block_id="b2",
            instance_id="gpu0",
            parent_hash="h_sys",
            own_hash="h_sys_ret",
        )
        sm.add_block(block1)
        sm.add_block(block2)

        # Query chain [h_sys, h_sys_ret, h_sys_ret_user] where last is not cached
        result = sm.query_prefix_chain(["h_sys", "h_sys_ret", "h_sys_ret_user"])
        assert result == "b2"  # Deepest available hit

    def test_hierarchical_prefix_chain_root_only(self):
        """Only system prompt (root) is cached."""
        sm = PrefixStateMachine()

        block1 = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h_sys",
        )
        sm.add_block(block1)

        # Query chain where system_prompt exists, but retrieval + user_turn don't
        result = sm.query_prefix_chain(["h_sys", "h_sys_ret", "h_sys_ret_user"])
        assert result == "b1"  # Only root available

    def test_hierarchical_prefix_chain_no_hit(self):
        """None of the chain is cached."""
        sm = PrefixStateMachine()

        result = sm.query_prefix_chain(["h_sys", "h_sys_ret", "h_sys_ret_user"])
        assert result is None


class TestPinCountingAndEviction:
    """Test pin counting semantics and eviction constraints."""

    def test_increment_pin_count(self):
        sm = PrefixStateMachine()
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
        )
        sm.add_block(block)

        sm.increment_pin_count("b1")
        assert sm.get_block("b1").pin_count == 1

        sm.increment_pin_count("b1")
        assert sm.get_block("b1").pin_count == 2

    def test_decrement_pin_count(self):
        sm = PrefixStateMachine()
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
        )
        sm.add_block(block)
        sm.increment_pin_count("b1")
        sm.increment_pin_count("b1")

        sm.decrement_pin_count("b1")
        assert sm.get_block("b1").pin_count == 1

        sm.decrement_pin_count("b1")
        assert sm.get_block("b1").pin_count == 0

    def test_cannot_evict_pinned_block(self):
        sm = PrefixStateMachine()
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
        )
        sm.add_block(block)
        sm.increment_pin_count("b1")

        with pytest.raises(RuntimeError):
            sm.evict_block("b1")

        # After unpinning, eviction should succeed
        sm.decrement_pin_count("b1")
        sm.evict_block("b1")
        assert sm.get_block("b1") is None

    def test_can_evict_unpinned_block(self):
        sm = PrefixStateMachine()
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
        )
        sm.add_block(block)

        sm.evict_block("b1")
        assert sm.get_block("b1") is None
        # Chain should also be cleared
        assert sm.query_prefix_chain(["h1"]) is None

    def test_concurrent_access_scenario(self):
        """System prompt used by multiple requests simultaneously."""
        sm = PrefixStateMachine()
        sys_block = Block(
            block_id="b_sys",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h_sys",
        )
        sm.add_block(sys_block)

        # Request A uses system prompt
        sm.increment_pin_count("b_sys")
        assert sm.get_block("b_sys").pin_count == 1
        assert not sm.get_block("b_sys").is_evictable()

        # Request B also uses system prompt
        sm.increment_pin_count("b_sys")
        assert sm.get_block("b_sys").pin_count == 2
        assert not sm.get_block("b_sys").is_evictable()

        # Request A finishes
        sm.decrement_pin_count("b_sys")
        assert sm.get_block("b_sys").pin_count == 1
        assert not sm.get_block("b_sys").is_evictable()

        # Request B finishes
        sm.decrement_pin_count("b_sys")
        assert sm.get_block("b_sys").pin_count == 0
        assert sm.get_block("b_sys").is_evictable()

        # Now eviction is allowed
        sm.evict_block("b_sys")
        assert sm.get_block("b_sys") is None


class TestInstanceTracking:
    """Test instance heartbeats, reboot detection, and reconciliation."""

    def test_update_instance_state(self):
        sm = PrefixStateMachine()

        sm.update_instance_state("gpu0", epoch=1, state_hash="hash_v1")
        assert sm.instance_epochs["gpu0"] == 1
        assert sm.instance_state_hashes["gpu0"] == "hash_v1"

        # Update with new epoch
        sm.update_instance_state("gpu0", epoch=2, state_hash="hash_v2")
        assert sm.instance_epochs["gpu0"] == 2
        assert sm.instance_state_hashes["gpu0"] == "hash_v2"

    def test_detect_reboot(self):
        sm = PrefixStateMachine()

        sm.update_instance_state("gpu0", epoch=5, state_hash="hash_v5")

        # Epoch goes backward (reboot)
        assert sm.detect_reboot("gpu0", new_epoch=2) is True

        # Epoch goes forward (normal)
        assert sm.detect_reboot("gpu0", new_epoch=6) is False

        # Unknown instance (first time seeing it)
        assert sm.detect_reboot("gpu1", new_epoch=1) is False

    def test_clear_instance_blocks_on_reboot(self):
        sm = PrefixStateMachine()

        # Add blocks on gpu0
        b1 = Block(block_id="b1", instance_id="gpu0", parent_hash=None, own_hash="h1")
        b2 = Block(block_id="b2", instance_id="gpu0", parent_hash="h1", own_hash="h2")
        b3 = Block(block_id="b3", instance_id="gpu1", parent_hash=None, own_hash="h3")
        sm.add_block(b1)
        sm.add_block(b2)
        sm.add_block(b3)

        assert len(sm.blocks) == 3

        # Clear gpu0 after reboot
        sm.clear_instance_blocks("gpu0")

        assert sm.get_block("b1") is None
        assert sm.get_block("b2") is None
        assert sm.get_block("b3") is not None  # gpu1 block should remain

    def test_reconcile_instance_state_no_drift(self):
        sm = PrefixStateMachine()

        b1 = Block(block_id="b1", instance_id="gpu0", parent_hash=None, own_hash="h1")
        sm.add_block(b1)

        remote_blocks = {"b1": {"info": "..."}}
        to_remove, to_add = sm.reconcile_instance_state("gpu0", remote_blocks)

        assert to_remove == []
        assert to_add == []

    def test_reconcile_instance_state_with_drift(self):
        sm = PrefixStateMachine()

        b1 = Block(block_id="b1", instance_id="gpu0", parent_hash=None, own_hash="h1")
        b2 = Block(block_id="b2", instance_id="gpu0", parent_hash="h1", own_hash="h2")
        sm.add_block(b1)
        sm.add_block(b2)

        # Instance only has b1 (b2 was evicted but we didn't get the signal)
        remote_blocks = {"b1": {"info": "..."}}
        to_remove, to_add = sm.reconcile_instance_state("gpu0", remote_blocks)

        assert set(to_remove) == {"b2"}
        assert to_add == []
        assert sm.get_block("b1") is not None
        assert sm.get_block("b2") is None

    def test_reconcile_instance_state_instance_added_block(self):
        sm = PrefixStateMachine()

        b1 = Block(block_id="b1", instance_id="gpu0", parent_hash=None, own_hash="h1")
        sm.add_block(b1)

        # Instance has b1 and b2 (we haven't heard about b2 yet)
        remote_blocks = {"b1": {"info": "..."}, "b2": {"info": "..."}}
        to_remove, to_add = sm.reconcile_instance_state("gpu0", remote_blocks)

        assert to_remove == []
        assert set(to_add) == {"b2"}


class TestStats:
    """Test metrics and statistics."""

    def test_get_stats_empty(self):
        sm = PrefixStateMachine()
        stats = sm.get_stats()

        assert stats["num_blocks"] == 0
        assert stats["pinned_blocks"] == 0
        assert stats["evictable_blocks"] == 0
        assert stats["total_kv_cache_bytes"] == 0

    def test_get_stats_with_blocks(self):
        sm = PrefixStateMachine()

        b1 = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
            kv_cache_bytes=1000,
        )
        b2 = Block(
            block_id="b2",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h2",
            kv_cache_bytes=2000,
        )
        sm.add_block(b1)
        sm.add_block(b2)

        # Pin b1
        sm.increment_pin_count("b1")

        stats = sm.get_stats()
        assert stats["num_blocks"] == 2
        assert stats["pinned_blocks"] == 1
        assert stats["evictable_blocks"] == 1
        assert stats["total_kv_cache_bytes"] == 3000
        assert stats["total_pin_count"] == 1

    def test_get_instance_blocks(self):
        sm = PrefixStateMachine()

        b1 = Block(block_id="b1", instance_id="gpu0", parent_hash=None, own_hash="h1")
        b2 = Block(block_id="b2", instance_id="gpu0", parent_hash=None, own_hash="h2")
        b3 = Block(block_id="b3", instance_id="gpu1", parent_hash=None, own_hash="h3")
        sm.add_block(b1)
        sm.add_block(b2)
        sm.add_block(b3)

        gpu0_blocks = sm.get_instance_blocks("gpu0")
        assert len(gpu0_blocks) == 2
        assert all(b.instance_id == "gpu0" for b in gpu0_blocks)

        gpu1_blocks = sm.get_instance_blocks("gpu1")
        assert len(gpu1_blocks) == 1
        assert gpu1_blocks[0].instance_id == "gpu1"
