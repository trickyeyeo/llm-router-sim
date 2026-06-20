"""
Event-driven simulation loop: coordinates router, GPU instances, and state machine.

Instead of time-stepping uniformly, jumps to next event time.
This is orders of magnitude faster for sparse event rates.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import heapq

from router.prefix_state_machine import PrefixStateMachine, Block
from router.router import (
    LoadAwareRouter,
    LoadAwareTelemetryBroker,
    InstanceTelemetry,
    RoutingDecision as RouterRoutingDecision,
    RoutingStrategy,
)
from simulator.gpu_backend import GPUInstance, GPUInstanceConfig
from simulator.workload import Request, WorkloadGenerator


class EventType(Enum):
    """Types of events in the simulation."""
    ARRIVAL = "arrival"
    PREFILL_COMPLETE = "prefill_complete"
    DECODE_COMPLETE = "decode_complete"
    HEARTBEAT = "heartbeat"
    TRANSFER_COMPLETE = "transfer_complete"
    FAILURE = "failure"
    RECOVERY = "recovery"


@dataclass
class Event:
    """An event in the simulation."""
    time: float
    event_type: EventType
    sequence: int  # For stable ordering when times are equal
    request_id: Optional[str] = None
    instance_id: Optional[str] = None
    block_id: Optional[str] = None

    def __lt__(self, other):
        """For heap ordering."""
        if self.time != other.time:
            return self.time < other.time
        return self.sequence < other.sequence


# RoutingDecision imported from router.router
RoutingDecision = RouterRoutingDecision


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


# Simple stateful router: cache-aware but no load telemetry
class SimpleRouter:
    """
    Simple stateful router: sticky to cached instance, round-robin fallback.
    (Uses cache affinity but ignores load telemetry)
    """

    def __init__(self, state_machine: PrefixStateMachine, instances: List[str]):
        self.state_machine = state_machine
        self.instances = instances
        self.round_robin_index = 0

    def route(self, request: Request) -> RoutingDecision:
        """Route with cache affinity only."""
        cached_block_id = self.state_machine.query_prefix_chain(request.prefix_hashes)
        if cached_block_id:
            block = self.state_machine.get_block(cached_block_id)
            instance_id = block.instance_id
            return RoutingDecision(
                request_id=request.request_id,
                instance_id=instance_id,
                strategy=RoutingStrategy.CACHE_HIT,
                cached_block_id=cached_block_id,
                cache_hit=True,
            )
        else:
            instance_id = self.instances[self.round_robin_index % len(self.instances)]
            self.round_robin_index += 1
            return RoutingDecision(
                request_id=request.request_id,
                instance_id=instance_id,
                strategy=RoutingStrategy.LOAD_BALANCED,
                cached_block_id=None,
                cache_hit=False,
            )


class StatelessRouter:
    """
    Stateless router: pure round-robin, ignores prefix cache.
    (Baseline: no awareness of KV cache state)
    """

    def __init__(self, instances: List[str]):
        self.instances = instances
        self.round_robin_index = 0

    def route(self, request: Request) -> RoutingDecision:
        """Route via round-robin, ignoring cache."""
        instance_id = self.instances[self.round_robin_index % len(self.instances)]
        self.round_robin_index += 1
        return RoutingDecision(
            request_id=request.request_id,
            instance_id=instance_id,
            strategy=RoutingStrategy.LOAD_BALANCED,
            cached_block_id=None,
            cache_hit=False,
        )


class EventDrivenSimulation:
    """
    Event-driven simulation loop: jump to next event time instead of stepping uniformly.

    Much faster than time-stepped simulation for realistic request rates.
    """

    def __init__(
        self,
        workload_gen: WorkloadGenerator,
        instances_config: List[GPUInstanceConfig],
        heartbeat_interval_ms: float = 100.0,
        stateful: bool = True,
        failure_rate: float = 0.0,
        failure_recovery_time_ms: float = 5000.0,
        network_type: str = "rdma",
        enable_p2p_recovery: bool = True,
    ):
        self.workload_gen = workload_gen
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.current_time = 0.0
        self.stateful = stateful

        # Failure injection (Phase 3)
        self.failure_rate = failure_rate
        self.failure_recovery_time_ms = failure_recovery_time_ms
        self.network_type = network_type
        self.enable_p2p_recovery = enable_p2p_recovery

        # State machine
        self.state_machine = PrefixStateMachine()

        # GPU instances
        self.instances: Dict[str, GPUInstance] = {
            cfg.instance_id: GPUInstance(cfg) for cfg in instances_config
        }

        # Set network type for all instances
        for instance in self.instances.values():
            instance.network_type = network_type

        # Telemetry broker for NATS-style updates
        self.telemetry_broker = LoadAwareTelemetryBroker(overload_threshold=0.8)

        # Router: stateful (cache-aware) or stateless (round-robin only)
        if stateful:
            self.router = SimpleRouter(
                self.state_machine,
                list(self.instances.keys()),
            )
        else:
            self.router = StatelessRouter(list(self.instances.keys()))

        # Metrics (Phase 3)
        self.request_metrics: Dict[str, RequestMetrics] = {}
        self.routing_decisions: List[RoutingDecision] = []
        self.transfers_initiated = 0
        self.transfers_completed = 0
        self.transfers_failed = 0
        self.failures_injected = 0

        # Pending operations
        self.pending_prefills: Dict[str, Dict] = {}  # op_id → metadata
        self.active_requests: Dict[str, Tuple[Request, RoutingDecision]] = {}  # request_id → (request, decision)
        self.pending_transfers: Dict[str, Dict] = {}  # transfer_id → {block_id, target_instance, completion_time}

        # Operation counters
        self.operation_counter = 0
        self.event_sequence = 0

        # Event queue
        self.event_queue: List[Event] = []
        self.next_heartbeat_time = heartbeat_interval_ms
        self._pending_arrivals: Dict[str, Request] = {}  # Pregenerated requests for bootstrap

    def run(self, simulation_time_ms: float) -> None:
        """Run simulation until simulation_time_ms."""
        end_time = simulation_time_ms

        # Bootstrap: generate initial arrivals
        self._bootstrap_arrivals(end_time)

        # Schedule first heartbeat
        self._schedule_heartbeat(self.next_heartbeat_time)

        while self.event_queue and self.current_time < end_time:
            # Pop next event
            event = heapq.heappop(self.event_queue)

            # Jump to event time
            self.current_time = event.time

            if self.current_time > end_time:
                break

            # Handle event
            if event.event_type == EventType.ARRIVAL:
                self._handle_arrival_event(event)
            elif event.event_type == EventType.PREFILL_COMPLETE:
                self._handle_prefill_complete(event.request_id, event.block_id)
            elif event.event_type == EventType.DECODE_COMPLETE:
                self._handle_decode_complete(event.request_id)
            elif event.event_type == EventType.TRANSFER_COMPLETE:
                self._handle_transfer_complete(event)
            elif event.event_type == EventType.HEARTBEAT:
                self._send_heartbeats()
                self._check_recoveries()
                # Schedule next heartbeat
                self._schedule_heartbeat(self.current_time + self.heartbeat_interval_ms)

    def _bootstrap_arrivals(self, end_time: float) -> None:
        """Bootstrap: generate all arrivals upfront."""
        # Query workload generator for all arrivals up to end_time
        arrivals = self.workload_gen.generate_arrivals(end_time)

        # Schedule arrival events for each request
        for request in arrivals:
            if request.arrival_time <= end_time:
                self.event_sequence += 1
                event = Event(
                    time=request.arrival_time,
                    event_type=EventType.ARRIVAL,
                    sequence=self.event_sequence,
                    request_id=request.request_id,
                )
                heapq.heappush(self.event_queue, event)
                # Store request for later retrieval
                self._pending_arrivals = getattr(self, '_pending_arrivals', {})
                self._pending_arrivals[request.request_id] = request

    def _schedule_heartbeat(self, time: float) -> None:
        """Schedule a heartbeat event."""
        self.event_sequence += 1
        event = Event(
            time=time,
            event_type=EventType.HEARTBEAT,
            sequence=self.event_sequence,
        )
        heapq.heappush(self.event_queue, event)

    def _handle_arrival_event(self, event: Event) -> None:
        """Process arrival event by looking up the pregenerated request."""
        # Get the request that was pregenerated in bootstrap
        request_id = event.request_id
        pending_arrivals = getattr(self, '_pending_arrivals', {})

        if request_id in pending_arrivals:
            request = pending_arrivals[request_id]
            self._handle_request_arrival(request)

    def _handle_request_arrival(self, request: Request) -> None:
        """Handle a request that has arrived."""
        # Probabilistic failure injection (Phase 3)
        if self.failure_rate > 0.0:
            import random
            if random.random() < self.failure_rate:
                # Inject failure on a random instance
                instance_list = list(self.instances.values())
                if instance_list:
                    victim = random.choice(instance_list)
                    if victim.health_status == "healthy":
                        victim.inject_failure(
                            self.current_time,
                            self.failure_recovery_time_ms,
                            reason="request_triggered",
                        )
                        self.failures_injected += 1

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

            # Schedule prefill and get completion time
            completion_time = self._schedule_prefill(
                op_id,
                request.request_id,
                block_id,
                block_info.num_tokens,
                block_info.kv_cache_bytes,
                decision.instance_id,
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

            # Schedule completion event
            self.event_sequence += 1
            event = Event(
                time=completion_time,
                event_type=EventType.PREFILL_COMPLETE,
                sequence=self.event_sequence,
                request_id=request.request_id,
                block_id=block_id,
                instance_id=decision.instance_id,
            )
            heapq.heappush(self.event_queue, event)

        # If all blocks are cached, start decode immediately
        if prefill_block_start >= len(request.prefix_blocks):
            self._start_decode(request, decision)

        self.active_requests[request.request_id] = (request, decision)

    def _schedule_prefill(
        self,
        operation_id: str,
        request_id: str,
        block_id: str,
        num_tokens: int,
        kv_cache_bytes: int,
        instance_id: str,
    ) -> float:
        """
        Schedule a prefill operation and return completion time.

        Does NOT add block to instance yet; that happens on completion event.
        """
        instance = self.instances[instance_id]

        # Calculate prefill time
        prefill_throughput_tokens_per_ms = (
            instance.config.prefill_throughput_tokens_per_sec / 1000.0
        )
        prefill_time_ms = num_tokens / prefill_throughput_tokens_per_ms
        completion_time = self.current_time + prefill_time_ms

        return completion_time

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

        # Add block to GPU instance HBM
        instance.add_block(block_id, op_metadata["block_info"].kv_cache_bytes, self.current_time)

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

        # Estimate decode time: target_tokens * latency_per_token_ms
        decode_time_ms = request.target_output_tokens * instance.config.decode_latency_per_token_ms
        decode_complete_time = self.current_time + decode_time_ms

        self.request_metrics[request.request_id].decode_start_time = self.current_time

        # Schedule decode complete event
        self.event_sequence += 1
        event = Event(
            time=decode_complete_time,
            event_type=EventType.DECODE_COMPLETE,
            sequence=self.event_sequence,
            request_id=request.request_id,
            instance_id=decision.instance_id,
        )
        heapq.heappush(self.event_queue, event)

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
        """Send periodic heartbeats from instances to state machine and telemetry broker."""
        for instance in self.instances.values():
            telemetry_dict = instance.get_telemetry()

            # Detect reboot (epoch change) and clear blocks
            old_epoch = self.state_machine.instance_epochs.get(instance.instance_id, telemetry_dict["epoch"])
            if telemetry_dict["epoch"] > old_epoch:
                self.state_machine.clear_instance_blocks(instance.instance_id)

            # Update state machine for reconciliation
            self.state_machine.update_instance_state(
                instance.instance_id,
                telemetry_dict["epoch"],
                telemetry_dict["state_hash"],
            )

            # Publish to telemetry broker for routing decisions (Phase 3: include health)
            telemetry = InstanceTelemetry(
                instance_id=instance.instance_id,
                epoch=telemetry_dict["epoch"],
                hbm_utilization=telemetry_dict["hbm_utilization"],
                queue_depth=telemetry_dict["num_decode_requests"],
                num_cached_blocks=telemetry_dict["num_blocks"],
                state_hash=telemetry_dict["state_hash"],
                timestamp=self.current_time,
                health_status=telemetry_dict["health_status"],
                failure_reason=telemetry_dict["failure_reason"],
                network_type=telemetry_dict["network_type"],
                prefill_queue_depth=telemetry_dict["num_prefill_queue"],
                decode_queue_depth=telemetry_dict["num_decode_requests"],
            )
            self.telemetry_broker.publish_telemetry(telemetry)

    def _check_recoveries(self) -> None:
        """Check if any failed instances should recover (Phase 3)."""
        for instance in self.instances.values():
            if instance.check_recovery(self.current_time):
                # Instance recovered, clear its blocks from state machine
                self.state_machine.clear_instance_blocks(instance.instance_id)

    def _handle_transfer_complete(self, event: Event) -> None:
        """Handle completion of a P2P KV block transfer (Phase 3)."""
        # For now, transfers are simple: just mark as complete
        # In a real system, this would validate the transfer and mark block as ready
        if event.instance_id and event.block_id:
            transfer_key = f"{event.instance_id}_{event.block_id}"
            if transfer_key in self.pending_transfers:
                self.transfers_completed += 1
                del self.pending_transfers[transfer_key]

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

        # Count routing strategies
        from router.router import RoutingStrategy
        strategy_counts = {}
        for d in self.routing_decisions:
            strategy = getattr(d, "strategy", None)
            if strategy:
                strategy_counts[strategy.value] = strategy_counts.get(strategy.value, 0) + 1

        if not latencies:
            return {
                "num_requests": len(self.request_metrics),
                "completed_requests": 0,
                "cache_hit_rate": 0.0,
                "routing_strategies": strategy_counts,
            }

        latencies.sort()
        ttfts.sort()

        return {
            "num_requests": len(self.request_metrics),
            "completed_requests": len(latencies),
            "cache_hit_rate": cache_hits / len(self.routing_decisions)
            if self.routing_decisions
            else 0.0,
            "routing_strategies": strategy_counts,
            # Phase 3: Failure and transfer metrics
            "failures_injected": self.failures_injected,
            "transfers_initiated": self.transfers_initiated,
            "transfers_completed": self.transfers_completed,
            "transfers_failed": self.transfers_failed,
            "network_type": self.network_type,
            "e2e_latency_ms": {
                "min": min(latencies),
                "max": max(latencies),
                "avg": sum(latencies) / len(latencies),
                "p50": latencies[len(latencies) // 2],
                "p99": latencies[int(len(latencies) * 0.99)] if len(latencies) > 100 else latencies[-1],
            },
            "ttft_ms": {
                "min": min(ttfts),
                "max": max(ttfts),
                "avg": sum(ttfts) / len(ttfts),
                "p50": ttfts[len(ttfts) // 2],
                "p99": ttfts[int(len(ttfts) * 0.99)] if len(ttfts) > 100 else ttfts[-1],
            },
            "instance_telemetry": {
                iid: instance.get_telemetry()
                for iid, instance in self.instances.items()
            },
        }
