"""
Load-aware router with NATS-style telemetry.

Routes requests based on:
1. Prefix cache hits (sticky affinity)
2. Load (HBM utilization, queue depth)
3. Health status (detects failures via epoch/heartbeat)
4. P2P transfer viability (compares transfer cost vs prefill)
5. Graceful fallback when preferred instance unavailable
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import random


@dataclass
class RouteScore:
    """Scoring result for a routing decision."""
    instance_id: str
    cache_value: float  # Value from cached prefix (prefill time saved)
    load_penalty: float  # Penalty from queue depth + HBM utilization
    noise: float  # Random tie-breaking noise
    total_score: float  # cache_value - load_penalty + noise
    matched_tokens: int  # Tokens from prefix cache match
    prefill_time_saved_ms: float  # Estimated time saved by cache hit


@dataclass
class InstanceTelemetry:
    """NATS-style telemetry from a GPU instance."""

    instance_id: str
    epoch: int
    hbm_utilization: float  # 0.0 to 1.0
    queue_depth: int  # Total number of requests queued (prefill + decode)
    num_cached_blocks: int  # Number of KV blocks cached
    state_hash: str  # For reconciliation
    timestamp: float = 0.0  # Simulation time when telemetry was received
    health_status: str = "healthy"  # "healthy" | "degraded" | "failed"
    failure_reason: Optional[str] = None  # Reason for degraded/failed state
    network_type: str = "rdma"  # "rdma" or "tcp" for P2P transfers
    # Separate queue tracking for scoring-based routing (prevents thundering herds)
    prefill_queue_depth: int = 0  # Requests waiting for prefill (high latency cost)
    decode_queue_depth: int = 0  # Requests in active decode (low latency cost)


class RoutingStrategy(Enum):
    """Routing strategy used for a request."""
    CACHE_HIT = "cache_hit"  # Routed to instance with cached prefix
    LOAD_BALANCED = "load_balanced"  # Routed to lowest-utilization instance
    AFFINITY_DEGRADED = "affinity_degraded"  # Preferred instance overloaded, fallback used


@dataclass
class RoutingDecision:
    """Result of routing a request."""

    request_id: str
    instance_id: str
    strategy: RoutingStrategy
    cached_block_id: Optional[str] = None
    cache_hit: bool = False
    # Telemetry snapshot at time of routing
    instance_hbm_utilization: float = 0.0
    instance_queue_depth: int = 0


class LoadAwareTelemetryBroker:
    """
    In-memory broker for NATS-style telemetry.

    Instances publish heartbeats; router subscribes and caches latest state.
    """

    def __init__(self, overload_threshold: float = 0.8):
        """
        Args:
            overload_threshold: HBM utilization threshold (>= this = overloaded)
        """
        self.overload_threshold = overload_threshold
        self.latest_telemetry: Dict[str, InstanceTelemetry] = {}

    def publish_telemetry(self, telemetry: InstanceTelemetry) -> None:
        """Instance publishes a telemetry update."""
        self.latest_telemetry[telemetry.instance_id] = telemetry

    def get_instance_telemetry(self, instance_id: str) -> Optional[InstanceTelemetry]:
        """Get latest telemetry for an instance."""
        return self.latest_telemetry.get(instance_id)

    def is_overloaded(self, instance_id: str) -> bool:
        """Check if instance is overloaded (HBM utilization >= threshold)."""
        telemetry = self.get_instance_telemetry(instance_id)
        if telemetry is None:
            return False  # No telemetry yet, assume not overloaded
        return telemetry.hbm_utilization >= self.overload_threshold

    def get_least_loaded_instance(self, candidates: List[str]) -> str:
        """
        Select instance with lowest HBM utilization.

        Args:
            candidates: List of instance IDs to choose from

        Returns:
            instance_id of least-loaded instance (or first if no telemetry)
        """
        if not candidates:
            return None

        best_instance = candidates[0]
        best_utilization = float('inf')

        for instance_id in candidates:
            telemetry = self.get_instance_telemetry(instance_id)
            utilization = telemetry.hbm_utilization if telemetry else 0.0
            if utilization < best_utilization:
                best_utilization = utilization
                best_instance = instance_id

        return best_instance


class LoadAwareRouter:
    """
    Load-aware router: routes based on cache affinity with load-balancing fallback.

    Strategy:
    1. Check if request prefix is cached (state machine)
    2. If cached and instance healthy and not overloaded: route to cached instance (CACHE_HIT)
    3. If cached but instance degraded/failed: evaluate transfer viability or fallback
    4. If cached but instance overloaded: route to least-loaded instance (AFFINITY_DEGRADED)
    5. If not cached: route to least-loaded healthy instance (LOAD_BALANCED)
    """

    def __init__(
        self,
        state_machine,
        instances: List[str],
        telemetry_broker: LoadAwareTelemetryBroker,
        routing_weights=None,
    ):
        self.state_machine = state_machine
        self.instances = instances
        self.telemetry_broker = telemetry_broker
        self.transfer_counter = 0  # Counter for generating transfer IDs

        # Use provided weights or import defaults
        if routing_weights is None:
            from simulator.constants import DEFAULT_ROUTING_WEIGHTS
            routing_weights = DEFAULT_ROUTING_WEIGHTS
        self.weights = routing_weights

    def calculate_cache_value(
        self, matched_tokens: int, total_request_tokens: int, prefill_throughput: float
    ) -> Tuple[float, float]:
        """
        Calculate cache value as: (matched_tokens / total_tokens) * time_saved.

        Args:
            matched_tokens: Number of tokens from cache hit
            total_request_tokens: Total tokens in request
            prefill_throughput: Tokens per second for prefill (from GPU config)

        Returns:
            (cache_value, prefill_time_saved_ms)
        """
        if total_request_tokens == 0:
            return 0.0, 0.0

        # Tokens that still need to be prefilled
        tokens_to_prefill = total_request_tokens - matched_tokens

        # Time saved = time that would be spent prefilling matched tokens
        if prefill_throughput > 0:
            prefill_time_saved_ms = (matched_tokens / prefill_throughput) * 1000.0
        else:
            prefill_time_saved_ms = 0.0

        # Cache value: proportion of tokens matched * time saved
        cache_ratio = matched_tokens / total_request_tokens if total_request_tokens > 0 else 0.0
        cache_value = cache_ratio * prefill_time_saved_ms * self.weights.w_cache

        return cache_value, prefill_time_saved_ms

    def calculate_load_penalty(self, instance_id: str) -> float:
        """
        Calculate load penalty for an instance.

        Penalty = prefill_queue * w_prefill + decode_queue * w_decode + hbm * w_hbm

        Args:
            instance_id: GPU instance to score

        Returns:
            Load penalty (higher = more congested)
        """
        telemetry = self.telemetry_broker.get_instance_telemetry(instance_id)
        if not telemetry:
            return 0.0

        # Separate queue penalties (prefill requests much more expensive)
        prefill_penalty = telemetry.prefill_queue_depth * self.weights.w_prefill_queue
        decode_penalty = telemetry.decode_queue_depth * self.weights.w_decode_queue

        # HBM penalty (soft scaling, not binary threshold)
        hbm_penalty = telemetry.hbm_utilization * self.weights.w_hbm

        total_penalty = prefill_penalty + decode_penalty + hbm_penalty
        return total_penalty

    def score_instance_for_routing(
        self,
        instance_id: str,
        matched_tokens: int,
        total_request_tokens: int,
        prefill_throughput: float,
    ) -> RouteScore:
        """
        Score an instance for routing a request.

        Score = cache_value - load_penalty + noise

        Args:
            instance_id: GPU instance
            matched_tokens: Tokens from cache hit
            total_request_tokens: Total request tokens
            prefill_throughput: Prefill throughput (tok/sec)

        Returns:
            RouteScore with all scoring components
        """
        cache_value, prefill_time_saved = self.calculate_cache_value(
            matched_tokens, total_request_tokens, prefill_throughput
        )
        load_penalty = self.calculate_load_penalty(instance_id)

        # Placeholder: noise will be added during tie-breaking
        return RouteScore(
            instance_id=instance_id,
            cache_value=cache_value,
            load_penalty=load_penalty,
            noise=0.0,
            total_score=cache_value - load_penalty,
            matched_tokens=matched_tokens,
            prefill_time_saved_ms=prefill_time_saved,
        )

    def select_instance_with_tie_breaking(
        self, scores: List[RouteScore]
    ) -> RouteScore:
        """
        Select best-scoring instance with noise-based tie-breaking.

        If multiple instances score within noise_epsilon, add random noise to break ties.

        Args:
            scores: List of RouteScore objects for all instances

        Returns:
            Selected RouteScore with noise applied
        """
        if not scores:
            return None

        best_score = max(scores, key=lambda s: s.total_score)
        best_value = best_score.total_score

        # Find all scores within epsilon of the best
        tied_scores = [
            s for s in scores
            if abs(s.total_score - best_value) <= self.weights.noise_epsilon
        ]

        # If there's a tie, add noise and re-select
        if len(tied_scores) > 1:
            for score in tied_scores:
                score.noise = random.uniform(
                    -self.weights.noise_magnitude,
                    self.weights.noise_magnitude,
                )
                score.total_score = score.cache_value - score.load_penalty + score.noise

            # Re-select with noise applied
            best_score = max(tied_scores, key=lambda s: s.total_score)

        return best_score

    def evaluate_transfer_viability(
        self,
        block_size_bytes: int,
        prefix_tokens: int,
        target_instance_id: str,
    ) -> dict:
        """
        Evaluate if P2P transfer is faster than prefill.

        Args:
            block_size_bytes: Size of KV cache block
            prefix_tokens: Number of tokens in prefix
            target_instance_id: Instance receiving the block

        Returns:
            Dict with transfer_time_ms, prefill_time_ms, should_transfer
        """
        telemetry = self.telemetry_broker.get_instance_telemetry(target_instance_id)
        if not telemetry:
            return {
                "transfer_time_ms": 0.0,
                "prefill_time_ms": 0.0,
                "should_transfer": False,
            }

        # Prefill time: prefix_tokens / prefill_throughput_tokens_per_sec
        # This is approximate since we don't have throughput here, but router doesn't have it
        # For now, stub: assume 1000 tokens/sec as baseline
        prefill_throughput = 1000.0  # tokens/sec (will be refined in Phase 3)
        prefill_time_ms = (prefix_tokens / prefill_throughput) * 1000.0

        # Transfer time: block_size / bandwidth
        # Get network type from telemetry
        from simulator.constants import NETWORK_RDMA, NETWORK_TCP

        network_config = NETWORK_RDMA if telemetry.network_type == "rdma" else NETWORK_TCP
        transfer_time_ms = block_size_bytes / network_config.bandwidth_bytes_per_ms

        return {
            "transfer_time_ms": transfer_time_ms,
            "prefill_time_ms": prefill_time_ms,
            "should_transfer": transfer_time_ms < prefill_time_ms,
        }

    def find_alternate_source_instance(self, block_id: str, failed_instance: str) -> Optional[str]:
        """
        Find another instance that has the given block (for transfer during failure).

        Args:
            block_id: Block to find
            failed_instance: Instance we're avoiding

        Returns:
            instance_id of alternate source, or None if no other instance has block
        """
        block = self.state_machine.get_block(block_id)
        if not block:
            return None

        # For now, this is a stub: in Phase 3, we'll track block replicas
        # For single-replica mode (current), only one instance has the block
        # So this will always return None unless we implement proactive replication
        return None

    def route(self, request) -> RoutingDecision:
        """
        Route a request using scoring-based logic (cache value - load penalty).

        Scoring prevents thundering herds by penalizing queue depth and HBM load,
        allowing trade-off between cache hits and load distribution.

        Score = (matched_tokens / total_tokens) * time_saved * w_cache
              - (prefill_queue * w_prefill + decode_queue * w_decode + hbm * w_hbm)
              + noise (for tie-breaking)

        Args:
            request: Request object with prefix_hashes, request_id

        Returns:
            RoutingDecision with routing strategy and telemetry snapshot
        """
        # Query prefix cache for match
        cached_block_id = self.state_machine.query_prefix_chain(request.prefix_hashes)

        # Find which instance has the cached block (if any)
        cache_owner_instance = None
        matched_tokens = 0
        if cached_block_id:
            block = self.state_machine.get_block(cached_block_id)
            cache_owner_instance = block.instance_id
            matched_tokens = block.prefix_tokens

        # Extract request parameters for scoring
        total_tokens = sum(pb.num_tokens for pb in request.prefix_blocks) + request.target_output_tokens

        # Score all instances, prioritizing healthy ones
        scores = []
        scores_degraded = []
        prefill_throughput = 1000.0  # Tokens/sec (will be refined per-model)

        for instance_id in self.instances:
            telemetry = self.telemetry_broker.get_instance_telemetry(instance_id)

            # Only give cache value to the instance that actually has the block
            instance_matched_tokens = matched_tokens if instance_id == cache_owner_instance else 0

            score = self.score_instance_for_routing(
                instance_id,
                instance_matched_tokens,
                total_tokens,
                prefill_throughput,
            )

            # Separate healthy from degraded/failed (but always score cache owner for transfer decisions)
            if telemetry and telemetry.health_status != "healthy":
                scores_degraded.append(score)
            else:
                scores.append(score)

        # Use degraded instances only if no healthy instances available
        if not scores and scores_degraded:
            scores = scores_degraded

        # Select best instance with tie-breaking noise
        best_score = self.select_instance_with_tie_breaking(scores)

        if not best_score:
            # Fallback to first instance (shouldn't happen)
            best_score = scores[0] if scores else RouteScore(
                instance_id=self.instances[0],
                cache_value=0.0,
                load_penalty=0.0,
                noise=0.0,
                total_score=0.0,
                matched_tokens=0,
                prefill_time_saved_ms=0.0,
            )

        selected_instance = best_score.instance_id
        selected_telemetry = self.telemetry_broker.get_instance_telemetry(selected_instance)

        # Determine routing strategy and cache_hit based on where we're actually routing
        # cache_hit is true ONLY if:
        # 1. There's a cached block AND
        # 2. We're routing to the instance that HAS that cached block
        if cached_block_id and best_score.matched_tokens > 0:
            block = self.state_machine.get_block(cached_block_id)
            if block and block.instance_id == selected_instance:
                # Actually routing to the instance with cache
                strategy = RoutingStrategy.CACHE_HIT
                cache_hit = True
            else:
                # Cache exists but we're routing elsewhere for load balancing
                strategy = RoutingStrategy.AFFINITY_DEGRADED
                cache_hit = False
                cached_block_id = None  # Don't report cache hit if not using it
        else:
            strategy = RoutingStrategy.LOAD_BALANCED
            cache_hit = False
            cached_block_id = None

        return RoutingDecision(
            request_id=request.request_id,
            instance_id=selected_instance,
            strategy=strategy,
            cached_block_id=cached_block_id if cache_hit else None,
            cache_hit=cache_hit,
            instance_hbm_utilization=selected_telemetry.hbm_utilization if selected_telemetry else 0.0,
            instance_queue_depth=selected_telemetry.queue_depth if selected_telemetry else 0,
        )


class FailureSimulator:
    """
    Stub for Phase 3: GPU failure injection and recovery modeling.

    Will support:
    - Random failure injection (probabilistic)
    - Cascading failures (when one GPU fails, others may follow)
    - Periodic failures (deterministic timing)
    - Recovery time modeling
    - Failure detection latency (via heartbeat interval)
    """

    def __init__(self, failure_config):
        """
        Args:
            failure_config: FailureInjectionConfig from constants
        """
        self.enabled = failure_config.enabled
        self.failure_rate = failure_config.failure_rate
        self.failure_detection_delay_ms = failure_config.failure_detection_delay_ms
        self.failure_recovery_time_ms = failure_config.failure_recovery_time_ms
        self.failure_type = failure_config.failure_type
        self.instance_failure_times: Dict[str, float] = {}  # instance_id → time when it failed
        self.instance_recovery_times: Dict[str, float] = {}  # instance_id → time when it recovers

    def should_inject_failure(self) -> bool:
        """Determine if failure should occur on this request (Phase 3)."""
        if not self.enabled or self.failure_rate <= 0:
            return False
        return random.random() < self.failure_rate

    def inject_failure(self, instance_id: str, current_time: float, reason: str = "random") -> None:
        """Record a failure event (Phase 3)."""
        self.instance_failure_times[instance_id] = current_time

    def recover_instance(self, instance_id: str, current_time: float) -> None:
        """Record recovery of a failed instance (Phase 3)."""
        self.instance_recovery_times[instance_id] = current_time

    def is_instance_failed(self, instance_id: str, current_time: float) -> bool:
        """Check if instance is currently failed (Phase 3)."""
        if instance_id not in self.instance_failure_times:
            return False
        failure_time = self.instance_failure_times[instance_id]
        recovery_time = self.instance_recovery_times.get(instance_id, failure_time + self.failure_recovery_time_ms)
        return failure_time <= current_time < recovery_time

    def get_failure_reason(self, instance_id: str) -> Optional[str]:
        """Get reason for failure (Phase 3)."""
        if instance_id in self.instance_failure_times:
            return f"failure_at_{self.instance_failure_times[instance_id]}"
        return None
