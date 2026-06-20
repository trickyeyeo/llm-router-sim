"""
Test transfer viability evaluation and health-aware routing.

Tests P2P KV block transfer decision logic and graceful degradation on failures.
"""

import pytest
from router.prefix_state_machine import PrefixStateMachine, Block, TransferState
from router.router import LoadAwareRouter, LoadAwareTelemetryBroker, InstanceTelemetry, RoutingStrategy
from simulator.workload import Request, PrefixBlock


@pytest.fixture
def state_machine():
    return PrefixStateMachine()


@pytest.fixture
def telemetry_broker():
    return LoadAwareTelemetryBroker(overload_threshold=0.8)


@pytest.fixture
def router(state_machine, telemetry_broker):
    instances = ["gpu0", "gpu1"]
    return LoadAwareRouter(state_machine, instances, telemetry_broker)


def create_request(request_id: str, prefix_hashes: list) -> Request:
    """Create a mock request with given prefix hashes."""
    prefix_blocks = [
        PrefixBlock(
            name="system",
            hash_value=prefix_hashes[0],
            num_tokens=512,
            kv_cache_bytes=512 * 256,
        )
    ]
    if len(prefix_hashes) > 1:
        prefix_blocks.append(
            PrefixBlock(
                name="query",
                hash_value=prefix_hashes[1],
                num_tokens=128,
                kv_cache_bytes=128 * 256,
            )
        )

    return Request(
        request_id=request_id,
        arrival_time=0.0,
        prefix_blocks=prefix_blocks,
        target_output_tokens=256,
        model_id="H100-405B",
    )


class TestTransferViability:
    """Test P2P transfer viability evaluation."""

    def test_evaluate_transfer_rdma_faster_than_prefill(self, router, telemetry_broker):
        """RDMA transfer should be faster than prefill for small blocks."""
        # Set up RDMA network on gpu0
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.5,
                queue_depth=2,
                num_cached_blocks=5,
                state_hash="hash1",
                network_type="rdma",
            )
        )

        # Small block: 64KB
        # With RDMA at 12,500 bytes/ms: ~5ms
        # With 1000 tok/sec prefill: ~1 second for 1000 tokens
        result = router.evaluate_transfer_viability(
            block_size_bytes=64_000,  # 64KB
            prefix_tokens=1000,
            target_instance_id="gpu0",
        )
        assert result["transfer_time_ms"] < result["prefill_time_ms"]
        assert result["should_transfer"] is True

    def test_evaluate_transfer_tcp_slower_than_prefill(self, router, telemetry_broker):
        """TCP transfer might be slower than prefill for large blocks."""
        # Set up TCP network
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.5,
                queue_depth=2,
                num_cached_blocks=5,
                state_hash="hash1",
                network_type="tcp",
            )
        )

        # Large block: 10MB
        # With TCP at 1,250 bytes/ms: ~8000ms (8 seconds)
        # With 1000 tok/sec: ~1 second for 1000 tokens
        result = router.evaluate_transfer_viability(
            block_size_bytes=10_000_000,  # 10MB
            prefix_tokens=1000,
            target_instance_id="gpu0",
        )
        # TCP transfer is slower than prefill
        assert result["transfer_time_ms"] > result["prefill_time_ms"]
        assert result["should_transfer"] is False

    def test_health_aware_routing_healthy_instance(self, state_machine, telemetry_broker, router):
        """Route to healthy instance with cache hit."""
        # Cache prefix on gpu0
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
            pin_count=0,
            prefix_tokens=512,
            kv_cache_bytes=128_000,
        )
        state_machine.add_block(block)

        # Mark gpu0 as healthy
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.3,
                queue_depth=2,
                num_cached_blocks=1,
                state_hash="hash1",
                health_status="healthy",
                network_type="rdma",
                prefill_queue_depth=2,
                decode_queue_depth=0,
            )
        )

        # Mark gpu1 as healthy but slightly more loaded (force preference to gpu0)
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu1",
                epoch=1,
                hbm_utilization=0.4,
                queue_depth=3,
                num_cached_blocks=0,
                state_hash="hash2",
                health_status="healthy",
                network_type="rdma",
                prefill_queue_depth=3,
                decode_queue_depth=0,
            )
        )

        request = create_request("req1", ["h1"])
        decision = router.route(request)

        assert decision.instance_id == "gpu0"
        assert decision.cache_hit is True
        assert decision.strategy == RoutingStrategy.CACHE_HIT

    def test_health_aware_routing_degraded_instance(self, state_machine, telemetry_broker, router):
        """Degrade to least-loaded instance when preferred instance is degraded."""
        # Cache prefix on gpu0
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
            pin_count=0,
            prefix_tokens=512,
            kv_cache_bytes=128_000,
        )
        state_machine.add_block(block)

        # Mark gpu0 as degraded
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.5,
                queue_depth=5,
                num_cached_blocks=1,
                state_hash="hash1",
                health_status="degraded",
                failure_reason="disk_error",
                network_type="rdma",
            )
        )

        # Mark gpu1 as healthy
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu1",
                epoch=1,
                hbm_utilization=0.2,
                queue_depth=1,
                num_cached_blocks=0,
                state_hash="hash2",
                health_status="healthy",
                network_type="rdma",
            )
        )

        request = create_request("req1", ["h1"])
        decision = router.route(request)

        # Should fallback to least-loaded healthy instance (gpu1)
        assert decision.instance_id == "gpu1"
        assert decision.cache_hit is False
        assert decision.strategy == RoutingStrategy.AFFINITY_DEGRADED

    def test_health_aware_routing_failed_instance(self, state_machine, telemetry_broker, router):
        """Avoid failed instances entirely."""
        # Cache prefix on gpu0
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
            pin_count=0,
            prefix_tokens=512,
            kv_cache_bytes=128_000,
        )
        state_machine.add_block(block)

        # Mark gpu0 as failed
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.0,
                queue_depth=0,
                num_cached_blocks=1,
                state_hash="hash1",
                health_status="failed",
                failure_reason="memory_failure",
                network_type="rdma",
            )
        )

        # Mark gpu1 as healthy
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu1",
                epoch=1,
                hbm_utilization=0.4,
                queue_depth=3,
                num_cached_blocks=2,
                state_hash="hash2",
                health_status="healthy",
                network_type="rdma",
            )
        )

        request = create_request("req1", ["h1"])
        decision = router.route(request)

        # Should route to healthy instance (gpu1), not failed gpu0
        assert decision.instance_id == "gpu1"
        assert decision.cache_hit is False
        assert decision.strategy == RoutingStrategy.AFFINITY_DEGRADED

    def test_transfer_state_tracking(self, state_machine):
        """Track P2P transfers in state machine."""
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
            pin_count=0,
            prefix_tokens=512,
            kv_cache_bytes=128_000,
        )
        state_machine.add_block(block)

        # Initiate transfer
        transfer = state_machine.initiate_transfer(
            transfer_id="t1",
            block_id="b1",
            source_instance="gpu0",
            target_instance="gpu1",
            kv_cache_bytes=128_000,
            start_time=0.0,
            estimated_complete_time=50.0,  # 50ms
        )

        assert transfer.status == "pending"
        assert transfer.block_id == "b1"
        assert len(state_machine.get_transfers_in_flight()) == 1

        # Complete transfer
        state_machine.complete_transfer("t1")
        assert len(state_machine.get_transfers_in_flight()) == 0

        # Check stats
        stats = state_machine.get_stats()
        assert stats["transfers_completed"] == 1
        assert stats["transfers_pending"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
