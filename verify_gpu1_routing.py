#!/usr/bin/env python3
"""
Verify that GPU1 actually receives routed requests when GPU0 fails.
Run the exact demo scenario and check GPU1 metrics.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from simulator.simulation_loop import EventDrivenSimulation
from simulator.workload import MultiTurnWorkload
from simulator.constants import create_gpu_instance_config, H100_80GB, LLAMA_70B

def create_workload(num_sessions, turns, seed=42):
    return MultiTurnWorkload(
        num_sessions=num_sessions,
        turns_per_session=turns,
        turn_interval_ms=1000.0,
        system_prompt_tokens=512,
        tokens_per_turn_q_and_a=384,
        user_query_tokens=128,
        output_tokens_mean=256,
        kv_cache_bytes_per_token=LLAMA_70B.kv_cache_bytes_per_token,
        seed=seed,
    )

def create_sim(num_sessions, turns, failure_rate, enable_p2p):
    instances_config = [
        create_gpu_instance_config("gpu0", H100_80GB, LLAMA_70B),
        create_gpu_instance_config("gpu1", H100_80GB, LLAMA_70B),
    ]
    workload = create_workload(num_sessions, turns, seed=42)
    return EventDrivenSimulation(
        workload_gen=workload,
        instances_config=instances_config,
        heartbeat_interval_ms=100.0,
        stateful=True,
        failure_rate=failure_rate,
        failure_recovery_time_ms=5000.0,
        network_type="rdma",
        enable_p2p_recovery=enable_p2p,
    )

print("=" * 70)
print("VERIFYING GPU1 RECEIVES REQUESTS WITH FAILURES")
print("=" * 70)
print()

# Graceful Degradation demo: 20 sessions, 2 turns, 20% failure rate
print("Running simulation: 20 sessions, 2 turns, 20% failure rate")
print()

sim = create_sim(20, 2, failure_rate=0.2, enable_p2p=False)
sim.run(35_000.0)

print("=== RESULTS ===")
print()
print(f"Total failures injected: {sim.failures_injected}")
print(f"Total requests: {len(sim.routing_decisions)}")
print()

# Count routing decisions by GPU
gpu0_count = sum(1 for d in sim.routing_decisions if d.instance_id == "gpu0")
gpu1_count = sum(1 for d in sim.routing_decisions if d.instance_id == "gpu1")

print(f"GPU0 received: {gpu0_count} requests")
print(f"GPU1 received: {gpu1_count} requests")
print()

# Count cache hits by GPU
gpu0_hits = sum(1 for d in sim.routing_decisions if d.instance_id == "gpu0" and d.cache_hit)
gpu1_hits = sum(1 for d in sim.routing_decisions if d.instance_id == "gpu1" and d.cache_hit)

print(f"GPU0 cache hits: {gpu0_hits}/{gpu0_count}")
print(f"GPU1 cache hits: {gpu1_hits}/{gpu1_count}")
print()

# Final block counts
gpu0_blocks = len(sim.instances["gpu0"].blocks)
gpu1_blocks = len(sim.instances["gpu1"].blocks)

print(f"GPU0 final blocks: {gpu0_blocks}")
print(f"GPU1 final blocks: {gpu1_blocks}")
print()

# Check GPU1 state
if gpu1_count > 0:
    print("✓ GPU1 DID receive routed requests")
    if gpu1_blocks > 0:
        print(f"✓ GPU1 accumulated {gpu1_blocks} blocks")
    else:
        print("⚠ WARNING: GPU1 received requests but has 0 blocks at end")
else:
    print("✗ GPU1 NEVER RECEIVED ANY REQUESTS")
    print("  → This means the router isn't routing to GPU1 after GPU0 fails")
    print("  → The health status update fix didn't work")
