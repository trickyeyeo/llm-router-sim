"""
FastAPI backend for LLM Router demo webapp.

Streams real-time simulation results to frontend via SSE.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Add parent directory to path to import simulation modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from simulator.simulation_loop import EventDrivenSimulation
from simulator.workload import MultiTurnWorkload
from simulator.constants import create_gpu_instance_config, H100_80GB, LLAMA_70B


app = FastAPI(title="LLM Router Demo")

# Enable CORS for frontend dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def create_workload(num_sessions: int, turns_per_session: int, seed: int = 42):
    """Create multi-turn workload."""
    return MultiTurnWorkload(
        num_sessions=num_sessions,
        turns_per_session=turns_per_session,
        turn_interval_ms=1000.0,
        system_prompt_tokens=512,
        tokens_per_turn_q_and_a=384,
        user_query_tokens=128,
        output_tokens_mean=256,
        kv_cache_bytes_per_token=LLAMA_70B.kv_cache_bytes_per_token,
        seed=seed,
    )


def create_simulation(
    num_sessions: int,
    turns_per_session: int,
    stateful: bool,
    failure_rate: float = 0.0,
    network_type: str = "rdma",
    enable_p2p_recovery: bool = True,
):
    """Create simulation instance."""
    instances_config = [
        create_gpu_instance_config("gpu0", H100_80GB, LLAMA_70B),
        create_gpu_instance_config("gpu1", H100_80GB, LLAMA_70B),
    ]

    workload = create_workload(num_sessions, turns_per_session, seed=42)

    return EventDrivenSimulation(
        workload_gen=workload,
        instances_config=instances_config,
        heartbeat_interval_ms=100.0,
        stateful=stateful,
        failure_rate=failure_rate,
        failure_recovery_time_ms=5000.0,
        network_type=network_type,
        enable_p2p_recovery=enable_p2p_recovery,
    )


def extract_gpu_metrics(sim):
    """Extract current GPU metrics from simulation."""
    metrics = {}

    # Calculate per-GPU cache hit rates from routing decisions
    gpu_cache_hits = {}
    gpu_total_requests = {}
    for decision in sim.routing_decisions:
        instance_id = decision.instance_id
        gpu_total_requests[instance_id] = gpu_total_requests.get(instance_id, 0) + 1
        if decision.cache_hit:
            gpu_cache_hits[instance_id] = gpu_cache_hits.get(instance_id, 0) + 1

    for instance_id, instance in sim.instances.items():
        telemetry = instance.get_telemetry()
        total = gpu_total_requests.get(instance_id, 1)
        hits = gpu_cache_hits.get(instance_id, 0)
        per_gpu_hit_rate = hits / total if total > 0 else 0.0

        metrics[instance_id] = {
            "hbm_utilization": telemetry["hbm_utilization"],
            "cache_hit_rate": per_gpu_hit_rate if sim.stateful else 0.0,
            "num_cached_blocks": telemetry["num_blocks"],
            "active_requests": len(instance.decode_requests),
        }
    return metrics


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/simulate")
async def simulate(
    num_sessions: int = Query(5, ge=1, le=100),
    turns_per_session: int = Query(5, ge=1, le=10),
    failure_rate: float = Query(0.0, ge=0.0, le=1.0),
    network_type: str = Query("rdma", regex="^(rdma|tcp)$"),
    enable_p2p_recovery: bool = Query(True),
):
    """
    Run simulations (stateless and stateful) and stream results.

    Query params:
    - num_sessions: number of concurrent conversation sessions (1-100)
    - turns_per_session: number of turns per session (1-10)
    - failure_rate: probability of GPU failure per request (0.0-1.0)
    - network_type: network technology for P2P transfers ("rdma" or "tcp")
    - enable_p2p_recovery: whether to enable P2P recovery for stateful sim (default: True)

    Streams SSE events with real-time metrics.
    """

    async def event_generator():
        # Create both simulations (Phase 3: pass failure_rate and network_type)
        sim_stateless = create_simulation(
            num_sessions, turns_per_session, stateful=False,
            failure_rate=failure_rate, network_type=network_type
        )
        sim_stateful = create_simulation(
            num_sessions, turns_per_session, stateful=True,
            failure_rate=failure_rate, network_type=network_type,
            enable_p2p_recovery=enable_p2p_recovery
        )

        # Simulation parameters
        sim_time = 35_000.0  # 35 seconds

        # Bootstrap arrivals
        sim_stateless._bootstrap_arrivals(sim_time)
        sim_stateful._bootstrap_arrivals(sim_time)

        # Schedule first heartbeats
        sim_stateless._schedule_heartbeat(sim_stateless.heartbeat_interval_ms)
        sim_stateful._schedule_heartbeat(sim_stateful.heartbeat_interval_ms)

        yield f"data: {json.dumps({'type': 'started'})}\n\n"

        # Run simulations step by step, yielding heartbeats
        while (
            sim_stateless.event_queue or sim_stateful.event_queue
        ) and sim_stateless.current_time < sim_time:
            # Step both simulations
            if sim_stateless.event_queue:
                import heapq

                event = heapq.heappop(sim_stateless.event_queue)
                sim_stateless.current_time = event.time
                if sim_stateless.current_time <= sim_time:
                    if event.event_type.value == "arrival":
                        sim_stateless._handle_arrival_event(event)
                    elif event.event_type.value == "prefill_complete":
                        sim_stateless._handle_prefill_complete(event.request_id, event.block_id)
                    elif event.event_type.value == "decode_complete":
                        sim_stateless._handle_decode_complete(event.request_id)
                    elif event.event_type.value == "transfer_complete":
                        sim_stateless._handle_transfer_complete(event)
                    elif event.event_type.value == "heartbeat":
                        sim_stateless._send_heartbeats()
                        sim_stateless._schedule_heartbeat(
                            sim_stateless.current_time + sim_stateless.heartbeat_interval_ms
                        )

            if sim_stateful.event_queue:
                import heapq

                event = heapq.heappop(sim_stateful.event_queue)
                sim_stateful.current_time = event.time
                if sim_stateful.current_time <= sim_time:
                    if event.event_type.value == "arrival":
                        sim_stateful._handle_arrival_event(event)
                    elif event.event_type.value == "prefill_complete":
                        sim_stateful._handle_prefill_complete(event.request_id, event.block_id)
                    elif event.event_type.value == "decode_complete":
                        sim_stateful._handle_decode_complete(event.request_id)
                    elif event.event_type.value == "transfer_complete":
                        sim_stateful._handle_transfer_complete(event)
                    elif event.event_type.value == "heartbeat":
                        sim_stateful._send_heartbeats()
                        sim_stateful._schedule_heartbeat(
                            sim_stateful.current_time + sim_stateful.heartbeat_interval_ms
                        )

            # Emit heartbeat event periodically
            if int(sim_stateless.current_time) % 1000 == 0:  # Every 1 second
                progress = min(
                    sim_stateless.current_time / sim_time,
                    sim_stateful.current_time / sim_time,
                )

                heartbeat_data = {
                    "type": "heartbeat",
                    "progress": progress,
                    "current_time_ms": sim_stateless.current_time,
                    "total_time_ms": sim_time,
                    "stateless": {
                        "gpus": extract_gpu_metrics(sim_stateless),
                        "requests": {
                            "generated": len(sim_stateless.request_metrics),
                            "completed": sum(
                                1
                                for m in sim_stateless.request_metrics.values()
                                if m.decode_complete_time is not None
                            ),
                        },
                    },
                    "stateful": {
                        "gpus": extract_gpu_metrics(sim_stateful),
                        "requests": {
                            "generated": len(sim_stateful.request_metrics),
                            "completed": sum(
                                1
                                for m in sim_stateful.request_metrics.values()
                                if m.decode_complete_time is not None
                            ),
                        },
                    },
                }
                yield f"data: {json.dumps(heartbeat_data)}\n\n"

            await asyncio.sleep(0.01)  # Yield control

        # Send final results
        metrics_stateless = sim_stateless.get_metrics_summary()
        metrics_stateful = sim_stateful.get_metrics_summary()

        final_data = {
            "type": "complete",
            "stateless": metrics_stateless,
            "stateful": metrics_stateful,
        }
        yield f"data: {json.dumps(final_data)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Mount static files AFTER API routes so /health and /simulate are accessible
dist_path = Path(__file__).parent / "dist"
if dist_path.exists():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
