#!/usr/bin/env python3
"""
Compare baseline (no P2P) vs with P2P recovery.
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

def run_test(enable_p2p):
    sim = create_sim(20, 2, failure_rate=0.2, enable_p2p=enable_p2p)
    sim.run(35_000.0)

    gpu0_count = sum(1 for d in sim.routing_decisions if d.instance_id == "gpu0")
    gpu1_count = sum(1 for d in sim.routing_decisions if d.instance_id == "gpu1")
    gpu1_hits = sum(1 for d in sim.routing_decisions if d.instance_id == "gpu1" and d.cache_hit)

    return {
        "failures": sim.failures_injected,
        "transfers_initiated": sim.transfers_initiated,
        "transfers_completed": sim.transfers_completed,
        "gpu0_requests": gpu0_count,
        "gpu1_requests": gpu1_count,
        "gpu1_hits": gpu1_hits,
        "gpu1_hit_rate": gpu1_hits / gpu1_count if gpu1_count > 0 else 0,
        "gpu0_blocks": len(sim.instances["gpu0"].blocks),
        "gpu1_blocks": len(sim.instances["gpu1"].blocks),
    }

print("=" * 70)
print("COMPARING BASELINE vs WITH P2P RECOVERY")
print("=" * 70)
print()

print("BASELINE (no P2P recovery):")
baseline = run_test(False)
print(f"  Failures: {baseline['failures']}")
print(f"  GPU0 requests: {baseline['gpu0_requests']}")
print(f"  GPU1 requests: {baseline['gpu1_requests']}")
print(f"  GPU1 cache hits: {baseline['gpu1_hits']}/{baseline['gpu1_requests']} ({baseline['gpu1_hit_rate']:.0%})")
print(f"  GPU0 blocks: {baseline['gpu0_blocks']}, GPU1 blocks: {baseline['gpu1_blocks']}")
print()

print("WITH P2P RECOVERY:")
with_p2p = run_test(True)
print(f"  Failures: {with_p2p['failures']}")
print(f"  Transfers initiated: {with_p2p['transfers_initiated']}")
print(f"  Transfers completed: {with_p2p['transfers_completed']}")
print(f"  GPU0 requests: {with_p2p['gpu0_requests']}")
print(f"  GPU1 requests: {with_p2p['gpu1_requests']}")
print(f"  GPU1 cache hits: {with_p2p['gpu1_hits']}/{with_p2p['gpu1_requests']} ({with_p2p['gpu1_hit_rate']:.0%})")
print(f"  GPU0 blocks: {with_p2p['gpu0_blocks']}, GPU1 blocks: {with_p2p['gpu1_blocks']}")
print()

print("=" * 70)
print("DIFFERENCE (with P2P - baseline):")
print("=" * 70)
print(f"GPU1 blocks: {with_p2p['gpu1_blocks']} vs {baseline['gpu1_blocks']} ({with_p2p['gpu1_blocks'] - baseline['gpu1_blocks']:+d})")
print(f"GPU1 cache hits: {with_p2p['gpu1_hits']} vs {baseline['gpu1_hits']} ({with_p2p['gpu1_hits'] - baseline['gpu1_hits']:+d})")
print(f"GPU1 hit rate: {with_p2p['gpu1_hit_rate']:.0%} vs {baseline['gpu1_hit_rate']:.0%}")

if with_p2p['transfers_completed'] > 0:
    print()
    print(f"✓ P2P transfers ARE WORKING ({with_p2p['transfers_completed']} completed)")
else:
    print()
    print(f"✗ P2P transfers NOT WORKING (0 completed, {with_p2p['transfers_initiated']} initiated)")
