"""
Quick test: small simulation to verify core logic works.
Uses realistic constants for H100 + Llama-70B.
"""

from simulator.simulation_loop import SimulationLoop
from simulator.workload import RAGWorkload
from simulator.constants import (
    create_gpu_instance_config,
    H100_80GB,
    LLAMA_70B,
)


def run_quick_test():
    """Run quick test with small workload."""

    # Single H100 with Llama-70B (more realistic than placeholder values)
    instances_config = [
        create_gpu_instance_config("gpu0", H100_80GB, LLAMA_70B),
    ]

    # Small workload: 10 req/sec, 40% retrieval overlap
    # KV cache size from Llama-70B: ~512KB per token
    workload = RAGWorkload(
        arrival_rate_requests_per_sec=10.0,  # 10 requests/sec (small)
        system_prompt_tokens=512,
        retrieval_context_tokens=2048,
        user_query_tokens=128,
        retrieval_reuse_probability=0.4,
        output_tokens_mean=256,
        kv_cache_bytes_per_token=LLAMA_70B.kv_cache_bytes_per_token,
        seed=42,
    )

    # Small simulation: 1 second
    sim = SimulationLoop(
        workload_gen=workload,
        instances_config=instances_config,
        heartbeat_interval_ms=100.0,
        time_step_ms=10.0,  # 10ms steps (larger) for speed
    )

    print("Running quick test for 1 second (simulated time)...")
    import time
    start = time.time()

    sim.run(simulation_time_ms=1000.0)

    elapsed = time.time() - start
    print(f"Simulation completed in {elapsed:.2f} seconds wall time")

    # Get metrics
    metrics = sim.get_metrics_summary()
    print(f"\nGenerated {metrics['num_requests']} requests")
    print(f"Completed {metrics['completed_requests']} requests")
    print(f"Cache hit rate: {metrics['cache_hit_rate']:.1%}")

    if metrics["completed_requests"] > 0:
        e2e = metrics["e2e_latency_ms"]
        ttft = metrics["ttft_ms"]
        print(f"\nE2E latency (ms): avg={e2e['avg']:.1f}, p50={e2e['p50']:.1f}, p99={e2e['p99']:.1f}")
        print(f"TTFT (ms): avg={ttft['avg']:.1f}, p50={ttft['p50']:.1f}, p99={ttft['p99']:.1f}")


if __name__ == "__main__":
    run_quick_test()
