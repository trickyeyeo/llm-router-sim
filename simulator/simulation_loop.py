"""
Simulation loop: coordinates router, GPU instances, and state machine.

Time-stepped execution:
1. Generate request arrivals
2. Route requests (query state machine, make routing decision)
3. Step GPU instances (execute prefill, decode, eviction)
4. Update state machine with results
5. Collect metrics
6. Advance time
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import time as wall_time

from router.prefix_state_machine import PrefixStateMachine, Block
from simulator.gpu_backend import GPUInstance, GPUInstanceConfig
from simulator.workload import Request, WorkloadGenerator


@dataclass
class RoutingDecision:
    """Result of routing a request."""

    request_id: str
    instance_id: str
    cached_block_id: Optional[str] = None  # If prefix hit, which block to reuse
    cache_hit: bool = False


@dataclass
class RequestMetrics:
    """Metrics for a single request."""

    request_id: str
    arrival_time: float
    routing_decision_time: float
    prefill_complete_time: Optional[float] = None
    decode_start_time: Optional[float] = None
    decode_complete_time: Optional[float] = None

    @property
    def ttft_ms(self) -> Optional[float]:
        """Time-to-first-token: from arrival to first decode token."""
        if self.decode_start_time is None:
            return None
        return self.decode_start_time - self.arrival_time

    @property
    def e2e_latency_ms(self) -> Optional[float]:
        """End-to-end latency: from arrival to completion."""
        if self.decode_complete_time is None:
            return None
        return self.decode_complete_time - self.arrival_time


class SimpleRouter:
    """
    Simple router: sticky to cached instance, round-robin fallback.
    """

    def __init__(self, state_machine: PrefixStateMachine, instances: List[str]):
        self.state_machine = state_machine
        self.instances = instances
        self.round_robin_index = 0

    def route(self, request: Request) -> RoutingDecision:
        """
        Route a request.

        Query state machine for prefix cache hit.
        If hit, route to that instance.
        Otherwise, round-robin.
        """
        # Query prefix cache
        cached_block_id = self.state_machine.query_prefix_chain(request.prefix_hashes)

        if cached_block_id:
            # Cache hit: route to instance holding this block
            block = self.state_machine.get_block(cached_block_id)
            instance_id = block.instance_id
            return RoutingDecision(
                request_id=request.request_id,
                instance_id=instance_id,
                cached_block_id=cached_block_id,
                cache_hit=True,
            )
        else:
            # Cache miss: round-robin
            instance_id = self.instances[self.round_robin_index % len(self.instances)]
            self.round_robin_index += 1
            return RoutingDecision(
                request_id=request.request_id,
                instance_id=instance_id,
                cached_block_id=None,
                cache_hit=False,
            )


class SimulationLoop:
    """
    Main simulation loop coordinator.
    """

    def __init__(
        self,
        workload_gen: WorkloadGenerator,
        instances_config: List[GPUInstanceConfig],
        heartbeat_interval_ms: float = 100.0,
        time_step_ms: float = 1.0,
    ):
        self.workload_gen = workload_gen
        self.time_step_ms = time_step_ms
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.current_time = 0.0

        # State machine
        self.state_machine = PrefixStateMachine()

        # GPU instances
        self.instances: Dict[str, GPUInstance] = {
            cfg.instance_id: GPUInstance(cfg) for cfg in instances_config
        }

        # Router
        self.router = SimpleRouter(self.state_machine, list(self.instances.keys()))

        # Metrics
        self.request_metrics: Dict[str, RequestMetrics] = {}
        self.routing_decisions: List[RoutingDecision] = []

        # Pending operations (tracking prefills and decodes)
        self.pending_prefills: Dict[str, Dict] = {}  # op_id → metadata
        self.active_requests: Dict[str, Tuple[Request, RoutingDecision]] = {}  # request_id → (request, decision)

        # Operation counters
        self.operation_counter = 0
        self.next_heartbeat_time = heartbeat_interval_ms

    def run(self, simulation_time_ms: float) -> None:
        """Run simulation until simulation_time_ms."""
        end_time = simulation_time_ms

        while self.current_time < end_time:
            # 1. Generate arrivals
            arrivals = self.workload_gen.generate_arrivals(self.current_time)
            for request in arrivals:
                self._handle_arrival(request)

            # 2. Step each GPU instance
            for instance in self.instances.values():
                events = instance.step(self.current_time)
                for event_type, request_id, block_id in events:
                    if event_type == "prefill_complete":
                        self._handle_prefill_complete(request_id, block_id)
                    elif event_type == "decode_complete":
                        self._handle_decode_complete(request_id)

            # 3. Periodic heartbeats
            if self.current_time >= self.next_heartbeat_time:
                self._send_heartbeats()
                self.next_heartbeat_time += self.heartbeat_interval_ms

            # Advance time
            self.current_time += self.time_step_ms

    def _handle_arrival(self, request: Request) -> None:
        """Handle a new request arrival."""
        # Route the request
        decision = self.router.route(request)
        self.routing_decisions.append(decision)

        # Create metrics entry
        self.request_metrics[request.request_id] = RequestMetrics(
            request_id=request.request_id,
            arrival_time=request.arrival_time,
            routing_decision_time=self.current_time,
        )

        # Increment pin counts for cached blocks (if hit)
        if decision.cache_hit:
            self.state_machine.increment_pin_count(decision.cached_block_id)

        # Schedule prefill operations for uncached prefix blocks
        instance = self.instances[decision.instance_id]
        prefill_block_start = 0

        if decision.cache_hit:
            # Find which block we cached up to
            block = self.state_machine.get_block(decision.cached_block_id)
            cached_block_idx = None
            for i, prefix_hash in enumerate(request.prefix_hashes):
                if prefix_hash == block.own_hash:
                    cached_block_idx = i
                    break

            if cached_block_idx is not None:
                prefill_block_start = cached_block_idx + 1

        # Schedule prefills for uncached blocks
        for i in range(prefill_block_start, len(request.prefix_blocks)):
            block_info = request.prefix_blocks[i]

            # Determine parent hash for chaining
            if i == 0:
                parent_hash = None
            else:
                parent_hash = request.prefix_blocks[i - 1].hash_value

            # Create operation ID and block ID
            self.operation_counter += 1
            op_id = f"prefill_{self.operation_counter}"
            block_id = f"block_{i}_{request.request_id}"

            # Schedule prefill
            instance.schedule_prefill(
                operation_id=op_id,
                request_id=request.request_id,
                block_id=block_id,
                num_tokens=block_info.num_tokens,
                kv_cache_bytes=block_info.kv_cache_bytes,
                current_time=self.current_time,
            )

            # Track this prefill operation
            self.pending_prefills[op_id] = {
                "request": request,
                "decision": decision,
                "block_idx": i,
                "block_info": block_info,
                "parent_hash": parent_hash,
                "block_id": block_id,
            }

        # If all blocks are cached, start decode immediately
        if prefill_block_start >= len(request.prefix_blocks):
            self._start_decode(request, decision)

        self.active_requests[request.request_id] = (request, decision)

    def _handle_prefill_complete(self, request_id: str, block_id: str) -> None:
        """Handle completion of a prefill operation."""
        if request_id not in self.active_requests:
            return

        request, decision = self.active_requests[request_id]
        instance = self.instances[decision.instance_id]

        # Find the corresponding prefill operation metadata
        op_metadata = None
        op_id_to_delete = None
        for op_id, metadata in list(self.pending_prefills.items()):
            if (
                metadata["request"].request_id == request_id
                and metadata["decision"].instance_id == decision.instance_id
                and metadata["block_id"] == block_id
            ):
                op_metadata = metadata
                op_id_to_delete = op_id
                break

        if op_metadata is None:
            return

        if op_id_to_delete:
            del self.pending_prefills[op_id_to_delete]

        # Add block to state machine
        new_block = Block(
            block_id=block_id,
            instance_id=decision.instance_id,
            parent_hash=op_metadata["parent_hash"],
            own_hash=op_metadata["block_info"].hash_value,
            pin_count=1,  # Pinned by this request
            prefix_tokens=op_metadata["block_info"].num_tokens,
            kv_cache_bytes=op_metadata["block_info"].kv_cache_bytes,
            model_id=instance.model_id,
            epoch=instance.epoch,
        )
        self.state_machine.add_block(new_block)
        instance.pin_block(block_id)
        instance.touch_block(block_id, self.current_time)

        # Check if all prefills are complete for this request
        remaining_prefills = sum(
            1 for metadata in self.pending_prefills.values()
            if metadata["request"].request_id == request_id
        )

        if remaining_prefills == 0:
            # All prefills done, start decode
            self._start_decode(request, decision)

    def _start_decode(self, request: Request, decision: RoutingDecision) -> None:
        """Start decode phase for a request."""
        instance = self.instances[decision.instance_id]
        instance.start_decode(request.request_id, request.target_output_tokens)

        self.request_metrics[request.request_id].decode_start_time = self.current_time

    def _handle_decode_complete(self, request_id: str) -> None:
        """Handle completion of a decode phase."""
        if request_id not in self.active_requests:
            return

        request, decision = self.active_requests[request_id]
        instance = self.instances[decision.instance_id]

        # Unpin all blocks used by this request
        for prefix_hash in request.prefix_hashes:
            if prefix_hash in self.state_machine.chains:
                block_id = self.state_machine.chains[prefix_hash]
                self.state_machine.decrement_pin_count(block_id)
                instance.unpin_block(block_id)

        # Record completion time
        self.request_metrics[request_id].decode_complete_time = self.current_time

        # Remove from active requests
        del self.active_requests[request_id]

    def _send_heartbeats(self) -> None:
        """Send periodic heartbeats from instances to state machine."""
        for instance in self.instances.values():
            telemetry = instance.get_telemetry()
            self.state_machine.update_instance_state(
                instance.instance_id,
                telemetry["epoch"],
                telemetry["state_hash"],
            )

    def get_metrics_summary(self) -> Dict:
        """Get aggregate metrics from simulation."""
        latencies = [
            m.e2e_latency_ms
            for m in self.request_metrics.values()
            if m.e2e_latency_ms is not None
        ]
        ttfts = [
            m.ttft_ms for m in self.request_metrics.values() if m.ttft_ms is not None
        ]

        cache_hits = sum(1 for d in self.routing_decisions if d.cache_hit)

        if not latencies:
            return {
                "num_requests": len(self.request_metrics),
                "completed_requests": 0,
                "cache_hit_rate": 0.0,
            }

        latencies.sort()
        ttfts.sort()

        return {
            "num_requests": len(self.request_metrics),
            "completed_requests": len(latencies),
            "cache_hit_rate": cache_hits / len(self.routing_decisions)
            if self.routing_decisions
            else 0.0,
            "e2e_latency_ms": {
                "min": min(latencies),
                "max": max(latencies),
                "avg": sum(latencies) / len(latencies),
                "p50": latencies[len(latencies) // 2],
                "p99": latencies[int(len(latencies) * 0.99)],
            },
            "ttft_ms": {
                "min": min(ttfts),
                "max": max(ttfts),
                "avg": sum(ttfts) / len(ttfts),
                "p50": ttfts[len(ttfts) // 2],
                "p99": ttfts[int(len(ttfts) * 0.99)],
            },
            "instance_telemetry": {
                iid: instance.get_telemetry()
                for iid, instance in self.instances.items()
            },
        }
