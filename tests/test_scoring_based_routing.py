"""
Test scoring-based routing logic that prevents thundering herds.

Verifies cache value calculation, load penalties, and tie-breaking.
"""

import pytest
from router.prefix_state_machine import PrefixStateMachine, Block
from router.router import LoadAwareRouter, LoadAwareTelemetryBroker, InstanceTelemetry, RouteScore
from simulator.workload import Request, PrefixBlock
from simulator.constants import DEFAULT_ROUTING_WEIGHTS, RoutingWeights


@pytest.fixture
def state_machine():
    return PrefixStateMachine()


@pytest.fixture
def telemetry_broker():
    return LoadAwareTelemetryBroker(overload_threshold=0.8)


@pytest.fixture
def router(state_machine, telemetry_broker):
    instances = ["gpu0", "gpu1", "gpu2"]
    return LoadAwareRouter(
        state_machine,
        instances,
        telemetry_broker,
        routing_weights=DEFAULT_ROUTING_WEIGHTS,
    )


def create_request(request_id: str, prefix_hashes: list, total_output_tokens: int = 256) -> Request:
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
        target_output_tokens=total_output_tokens,
        model_id="H100-405B",
    )


class TestCacheValueCalculation:
    """Test cache value scoring."""

    def test_no_cache_hit_zero_value(self, router):
        """Cache value should be 0 when no tokens matched."""
        cache_value, time_saved = router.calculate_cache_value(
            matched_tokens=0,
            total_request_tokens=1000,
            prefill_throughput=1000.0,
        )
        assert cache_value == 0.0
        assert time_saved == 0.0

    def test_full_cache_hit_maximum_value(self, router):
        """Full cache hit should give maximum value."""
        cache_value, time_saved = router.calculate_cache_value(
            matched_tokens=512,  # Full system prompt cached
            total_request_tokens=512 + 256,  # system + output
            prefill_throughput=1000.0,  # 1 sec per 1000 tokens
        )
        # Time saved = 512 tokens / 1000 tok/sec = 512ms
        assert time_saved == 512.0
        # Cache value = (512/768) * 512 * 1.0 = 342.67
        assert cache_value > 0.0
        assert cache_value == pytest.approx((512 / 768) * 512.0 * 1.0)

    def test_partial_cache_hit_proportional_value(self, router):
        """Partial cache hit should give proportional value."""
        cache_value_512, time_512 = router.calculate_cache_value(
            matched_tokens=512,
            total_request_tokens=1024,
            prefill_throughput=1000.0,
        )

        cache_value_256, time_256 = router.calculate_cache_value(
            matched_tokens=256,
            total_request_tokens=1024,
            prefill_throughput=1000.0,
        )

        # 512 tokens should be worth more than 256 tokens
        # But not exactly 2x because cache_value = ratio * time_saved * weight
        # For 512: (512/1024) * 512ms * 1.0 = 256
        # For 256: (256/1024) * 256ms * 1.0 = 64
        # Ratio is 4:1 (quadratic: more tokens = more time saved = exponential value)
        assert cache_value_512 > cache_value_256
        assert cache_value_512 == pytest.approx(4.0 * cache_value_256, rel=0.01)


class TestLoadPenaltyCalculation:
    """Test load penalty scoring."""

    def test_no_load_zero_penalty(self, router, telemetry_broker):
        """Empty instance should have zero load penalty."""
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.0,
                queue_depth=0,
                num_cached_blocks=0,
                state_hash="hash1",
                prefill_queue_depth=0,
                decode_queue_depth=0,
            )
        )

        penalty = router.calculate_load_penalty("gpu0")
        assert penalty == 0.0

    def test_prefill_queue_penalty_heavier_than_decode(self, router, telemetry_broker):
        """Prefill queue should be penalized more than decode queue."""
        # Instance with prefill queue
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.0,
                queue_depth=5,
                num_cached_blocks=0,
                state_hash="hash1",
                prefill_queue_depth=5,
                decode_queue_depth=0,
            )
        )

        # Instance with decode queue
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu1",
                epoch=1,
                hbm_utilization=0.0,
                queue_depth=5,
                num_cached_blocks=0,
                state_hash="hash2",
                prefill_queue_depth=0,
                decode_queue_depth=5,
            )
        )

        penalty_prefill = router.calculate_load_penalty("gpu0")
        penalty_decode = router.calculate_load_penalty("gpu1")

        # Prefill penalty should be much heavier (0.5 weight vs 0.1)
        # Ratio = (5 * 0.5) / (5 * 0.1) = 2.5 / 0.5 = 5.0
        assert penalty_prefill > penalty_decode
        assert penalty_prefill == pytest.approx(5.0 * penalty_decode)

    def test_hbm_penalty_soft_threshold(self, router, telemetry_broker):
        """HBM penalty should scale continuously, not binary at 0.8."""
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.4,
                queue_depth=0,
                num_cached_blocks=0,
                state_hash="hash1",
                prefill_queue_depth=0,
                decode_queue_depth=0,
            )
        )

        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu1",
                epoch=1,
                hbm_utilization=0.8,
                queue_depth=0,
                num_cached_blocks=0,
                state_hash="hash2",
                prefill_queue_depth=0,
                decode_queue_depth=0,
            )
        )

        penalty_low = router.calculate_load_penalty("gpu0")
        penalty_high = router.calculate_load_penalty("gpu1")

        # Both are penalized (soft), but high HBM is 2x penalty
        assert penalty_low > 0.0
        assert penalty_high > 0.0
        assert penalty_high == pytest.approx(2.0 * penalty_low)


class TestScoringAndTieBreaking:
    """Test instance scoring and tie-breaking."""

    def test_score_instance_combines_cache_and_load(self, router, telemetry_broker):
        """Score should combine cache value minus load penalty."""
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.0,
                queue_depth=0,
                num_cached_blocks=1,
                state_hash="hash1",
                prefill_queue_depth=0,
                decode_queue_depth=0,
            )
        )

        score = router.score_instance_for_routing(
            instance_id="gpu0",
            matched_tokens=256,
            total_request_tokens=512,
            prefill_throughput=1000.0,
        )

        assert score.instance_id == "gpu0"
        assert score.cache_value > 0.0
        assert score.load_penalty == 0.0
        assert score.total_score == score.cache_value

    def test_cache_value_vs_queue_tradeoff(self, router, telemetry_broker):
        """Cache advantage can be overcome by extreme queue congestion."""
        # GPU0: cache hit (256 tokens) but EXTREMELY heavy prefill queue (300 requests)
        # This simulates a severely congested GPU (cascade failure scenario, Phase 3)
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.95,  # Also high HBM
                queue_depth=300,
                num_cached_blocks=1,
                state_hash="hash1",
                prefill_queue_depth=300,
                decode_queue_depth=0,
            )
        )

        # GPU1: no cache but idle
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu1",
                epoch=1,
                hbm_utilization=0.0,
                queue_depth=0,
                num_cached_blocks=0,
                state_hash="hash2",
                prefill_queue_depth=0,
                decode_queue_depth=0,
            )
        )

        score_with_cache = router.score_instance_for_routing(
            instance_id="gpu0",
            matched_tokens=256,
            total_request_tokens=512,
            prefill_throughput=1000.0,
        )

        score_no_cache = router.score_instance_for_routing(
            instance_id="gpu1",
            matched_tokens=0,
            total_request_tokens=512,
            prefill_throughput=1000.0,
        )

        # Cache value = (256/512) * 256ms * 1.0 = 128
        # Queue penalty on gpu0 = 300 * 0.5 + 0.95 * 3.0 = 150 + 2.85 = 152.85
        # Score with cache = 128 - 152.85 = -24.85 (NEGATIVE)
        # Score without cache = 0 - 0 = 0
        # Now idle gpu1 is strongly preferred
        assert score_no_cache.total_score > score_with_cache.total_score

    def test_tie_breaking_with_noise(self, router, telemetry_broker):
        """When scores are similar, tie-breaking noise should pick different instances."""
        # Two identical GPUs
        for i in range(2):
            telemetry_broker.publish_telemetry(
                InstanceTelemetry(
                    instance_id=f"gpu{i}",
                    epoch=1,
                    hbm_utilization=0.3,
                    queue_depth=5,
                    num_cached_blocks=0,
                    state_hash=f"hash{i}",
                    prefill_queue_depth=5,
                    decode_queue_depth=0,
                )
            )

        scores = []
        for instance_id in ["gpu0", "gpu1"]:
            score = router.score_instance_for_routing(
                instance_id=instance_id,
                matched_tokens=0,
                total_request_tokens=512,
                prefill_throughput=1000.0,
            )
            scores.append(score)

        # Scores should be identical before tie-breaking
        assert scores[0].total_score == pytest.approx(scores[1].total_score)

        # After tie-breaking, one should be selected
        selected = router.select_instance_with_tie_breaking(scores)
        assert selected is not None
        # Noise should have been applied to at least one
        assert any(s.noise != 0.0 for s in scores)


class TestRoutingWithScoringLogic:
    """Test end-to-end routing with scoring."""

    def test_route_chooses_empty_over_cached_with_queue(self, state_machine, telemetry_broker):
        """Router should prefer empty instance over cached instance with heavy queue."""
        # Use only 2 instances for this test
        instances = ["gpu0", "gpu1"]
        router_2gpu = LoadAwareRouter(
            state_machine,
            instances,
            telemetry_broker,
            routing_weights=DEFAULT_ROUTING_WEIGHTS,
        )

        # Cache prefix on gpu0
        block = Block(
            block_id="b1",
            instance_id="gpu0",
            parent_hash=None,
            own_hash="h1",
            pin_count=0,
            prefix_tokens=256,
            kv_cache_bytes=64_000,
        )
        state_machine.add_block(block)

        # GPU0: has cache but heavy prefill queue (100 requests to overcome cache advantage)
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu0",
                epoch=1,
                hbm_utilization=0.85,
                queue_depth=100,
                num_cached_blocks=1,
                state_hash="hash1",
                health_status="healthy",
                prefill_queue_depth=100,
                decode_queue_depth=0,
            )
        )

        # GPU1: idle
        telemetry_broker.publish_telemetry(
            InstanceTelemetry(
                instance_id="gpu1",
                epoch=1,
                hbm_utilization=0.1,
                queue_depth=0,
                num_cached_blocks=0,
                state_hash="hash2",
                health_status="healthy",
                prefill_queue_depth=0,
                decode_queue_depth=0,
            )
        )

        request = create_request("req1", ["h1"])
        decision = router_2gpu.route(request)

        # Should route to idle gpu1 despite cache on gpu0
        # (100 * 0.5 + 0.85 * 3.0 = 50 + 2.55 = 52.55 penalty overcomes ~128 cache value)
        assert decision.instance_id == "gpu1"
        assert decision.cache_hit is False  # No cache on gpu1

    def test_route_all_balanced_distribution(self, telemetry_broker, router):
        """Multiple load-balanced requests should distribute across instances."""
        # Three identical idle instances
        for i in range(3):
            telemetry_broker.publish_telemetry(
                InstanceTelemetry(
                    instance_id=f"gpu{i}",
                    epoch=1,
                    hbm_utilization=0.1,
                    queue_depth=0,
                    num_cached_blocks=0,
                    state_hash=f"hash{i}",
                    health_status="healthy",
                    prefill_queue_depth=0,
                    decode_queue_depth=0,
                )
            )

        # Route 6 requests (no cache)
        instances_used = set()
        for i in range(6):
            request = create_request(f"req{i}", [f"h_new_{i}"])
            decision = router.route(request)
            instances_used.add(decision.instance_id)

        # Should use at least 2 instances (tie-breaking noise prevents all going to one)
        assert len(instances_used) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
