"""
Compare stateful (prefix-aware) vs stateless (round-robin) routing.

Measures impact of cache hit rate on:
- E2E latency (p50, p99)
- TTFT (time-to-first-token)
- Throughput (tokens/sec)
- Cache utilization
"""

from simulator.simulation_loop import EventDrivenSimulation
from simulator.workload import RAGWorkload
from simulator.constants import create_gpu_instance_config, H100_80GB, LLAMA_70B
import json


def run_comparison():
    """Run stateful vs stateless on identical RAG workload."""

    # Identical config for both runs
    instances_config = [
        create_gpu_instance_config("gpu0", H100_80GB, LLAMA_70B),
        create_gpu_instance_config("gpu1", H100_80GB, LLAMA_70B),
    ]

    # RAG workload: 10 req/sec, 40% retrieval overlap
    def make_workload():
        return RAGWorkload(
            arrival_rate_requests_per_sec=10.0,
            system_prompt_tokens=512,
            retrieval_context_tokens=2048,
            user_query_tokens=128,
            retrieval_reuse_probability=0.4,  # 40% overlap drives cache reuse
            output_tokens_mean=256,
            kv_cache_bytes_per_token=LLAMA_70B.kv_cache_bytes_per_token,
            seed=42,  # Same seed for reproducibility
        )

    sim_time = 30_000.0  # 30 seconds simulated

    # Run stateful (prefix-aware)
    print("=" * 70)
    print("STATEFUL (prefix-aware) routing")
    print("=" * 70)
    sim_stateful = EventDrivenSimulation(
        workload_gen=make_workload(),
        instances_config=instances_config,
        heartbeat_interval_ms=100.0,
        stateful=True,
    )
    sim_stateful.run(sim_time)
    metrics_stateful = sim_stateful.get_metrics_summary()

    # Run stateless (round-robin only)
    print("\n" + "=" * 70)
    print("STATELESS (round-robin) routing")
    print("=" * 70)
    sim_stateless = EventDrivenSimulation(
        workload_gen=make_workload(),
        instances_config=instances_config,
        heartbeat_interval_ms=100.0,
        stateful=False,
    )
    sim_stateless.run(sim_time)
    metrics_stateless = sim_stateless.get_metrics_summary()

    # Print results
    print("\n" + "=" * 70)
    print("COMPARISON RESULTS")
    print("=" * 70)

    print(f"\nRequests Generated: {metrics_stateful['num_requests']}")
    print(f"Requests Completed: {metrics_stateful['completed_requests']}")

    print(f"\n{'Metric':<30} {'Stateless':<20} {'Stateful':<20} {'Improvement'}")
    print("-" * 80)

    # Cache hit rate
    hit_rate_stateless = metrics_stateless.get("cache_hit_rate", 0.0)
    hit_rate_stateful = metrics_stateful.get("cache_hit_rate", 0.0)
    print(
        f"{'Cache Hit Rate':<30} {hit_rate_stateless:>18.1%} {hit_rate_stateful:>18.1%} "
        f"{hit_rate_stateful - hit_rate_stateless:>8.1%}"
    )

    # E2E Latency metrics
    e2e_stateless = metrics_stateless.get("e2e_latency_ms", {})
    e2e_stateful = metrics_stateful.get("e2e_latency_ms", {})

    if e2e_stateless and e2e_stateful:
        for key in ["p50", "p99", "avg"]:
            val_stateless = e2e_stateless.get(key, 0)
            val_stateful = e2e_stateful.get(key, 0)
            improvement = (val_stateless - val_stateful) / val_stateless * 100 if val_stateless else 0
            print(
                f"{'E2E Latency ' + key.upper():<30} {val_stateless:>18.1f}ms "
                f"{val_stateful:>18.1f}ms {improvement:>7.1f}% faster"
            )

    # TTFT metrics
    ttft_stateless = metrics_stateless.get("ttft_ms", {})
    ttft_stateful = metrics_stateful.get("ttft_ms", {})

    if ttft_stateless and ttft_stateful:
        for key in ["p50", "p99", "avg"]:
            val_stateless = ttft_stateless.get(key, 0)
            val_stateful = ttft_stateful.get(key, 0)
            improvement = (val_stateless - val_stateful) / val_stateless * 100 if val_stateless else 0
            print(
                f"{'TTFT ' + key.upper():<30} {val_stateless:>18.1f}ms "
                f"{val_stateful:>18.1f}ms {improvement:>7.1f}% faster"
            )

    # Throughput (derived from latency and num requests)
    completed = metrics_stateful["completed_requests"]
    if completed > 0:
        # Throughput: tokens/sec = total_output_tokens / total_time_sec
        output_tokens_per_request = 256  # Mean from workload
        total_output_tokens = completed * output_tokens_per_request
        throughput = total_output_tokens / (sim_time / 1000.0)

        print(f"\nThroughput: ~{throughput:.0f} tokens/sec")

    # Instance HBM utilization
    print(f"\nInstance Telemetry (Stateful):")
    for iid, telemetry in metrics_stateful.get("instance_telemetry", {}).items():
        print(
            f"  {iid}: {telemetry['hbm_utilization']:.1%} HBM, "
            f"{telemetry['num_blocks']} blocks cached"
        )

    print(f"\nInstance Telemetry (Stateless):")
    for iid, telemetry in metrics_stateless.get("instance_telemetry", {}).items():
        print(
            f"  {iid}: {telemetry['hbm_utilization']:.1%} HBM, "
            f"{telemetry['num_blocks']} blocks cached"
        )

    # Summary
    print("\n" + "=" * 70)
    print("KEY FINDINGS")
    print("=" * 70)
    print(f"✓ Cache hit rate with prefix-awareness: {hit_rate_stateful:.1%}")
    print(f"✓ E2E latency improvement: {(1 - e2e_stateful['avg']/e2e_stateless['avg'])*100:.1f}%")
    print(
        f"✓ P99 latency (tail latency) improvement: "
        f"{(1 - e2e_stateful['p99']/e2e_stateless['p99'])*100:.1f}%"
    )


if __name__ == "__main__":
    run_comparison()
