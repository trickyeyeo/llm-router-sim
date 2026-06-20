"""
Load-aware router with NATS-style telemetry.

Routes requests based on:
1. Prefix cache hits (sticky affinity)
2. Load (HBM utilization, queue depth)
3. Graceful fallback when preferred instance is overloaded
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


@dataclass
class InstanceTelemetry:
    """NATS-style telemetry from a GPU instance."""

    instance_id: str
    epoch: int
    hbm_utilization: float  # 0.0 to 1.0
    queue_depth: int  # Number of requests in decode queue
    num_cached_blocks: int  # Number of KV blocks cached
    state_hash: str  # For reconciliation
    timestamp: float = 0.0  # Simulation time when telemetry was received


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
    2. If cached and instance not overloaded: route to cached instance (CACHE_HIT)
    3. If cached but instance overloaded: route to least-loaded instance (AFFINITY_DEGRADED)
    4. If not cached: route to least-loaded instance (LOAD_BALANCED)
    """

    def __init__(
        self,
        state_machine,
        instances: List[str],
        telemetry_broker: LoadAwareTelemetryBroker,
    ):
        self.state_machine = state_machine
        self.instances = instances
        self.telemetry_broker = telemetry_broker

    def route(self, request) -> RoutingDecision:
        """
        Route a request based on cache affinity and load.

        Args:
            request: Request object with prefix_hashes, request_id

        Returns:
            RoutingDecision with routing strategy and telemetry snapshot
        """
        # Query prefix cache
        cached_block_id = self.state_machine.query_prefix_chain(request.prefix_hashes)

        if cached_block_id:
            # Prefix is cached somewhere
            block = self.state_machine.get_block(cached_block_id)
            preferred_instance = block.instance_id

            # Check if preferred instance is overloaded
            if not self.telemetry_broker.is_overloaded(preferred_instance):
                # Preferred instance has capacity, route there (cache hit)
                telemetry = self.telemetry_broker.get_instance_telemetry(preferred_instance)
                return RoutingDecision(
                    request_id=request.request_id,
                    instance_id=preferred_instance,
                    strategy=RoutingStrategy.CACHE_HIT,
                    cached_block_id=cached_block_id,
                    cache_hit=True,
                    instance_hbm_utilization=telemetry.hbm_utilization if telemetry else 0.0,
                    instance_queue_depth=telemetry.queue_depth if telemetry else 0,
                )
            else:
                # Preferred instance overloaded, degrade to load-balancing
                selected_instance = self.telemetry_broker.get_least_loaded_instance(self.instances)
                telemetry = self.telemetry_broker.get_instance_telemetry(selected_instance)
                return RoutingDecision(
                    request_id=request.request_id,
                    instance_id=selected_instance,
                    strategy=RoutingStrategy.AFFINITY_DEGRADED,
                    cached_block_id=cached_block_id,  # Still know about it, but routing elsewhere
                    cache_hit=False,
                    instance_hbm_utilization=telemetry.hbm_utilization if telemetry else 0.0,
                    instance_queue_depth=telemetry.queue_depth if telemetry else 0,
                )
        else:
            # Prefix not cached, route to least-loaded instance
            selected_instance = self.telemetry_broker.get_least_loaded_instance(self.instances)
            telemetry = self.telemetry_broker.get_instance_telemetry(selected_instance)
            return RoutingDecision(
                request_id=request.request_id,
                instance_id=selected_instance,
                strategy=RoutingStrategy.LOAD_BALANCED,
                cached_block_id=None,
                cache_hit=False,
                instance_hbm_utilization=telemetry.hbm_utilization if telemetry else 0.0,
                instance_queue_depth=telemetry.queue_depth if telemetry else 0,
            )
