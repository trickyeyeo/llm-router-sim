"""
Comparison: Stateful (prefix-aware) vs Stateless routing on RAG workload.

Demonstrates the value of tracking KV cache state for routing decisions.
"""

from simulator.simulation_loop import EventDrivenSimulation
from simulator.workload import RAGWorkload
from simulator.constants import create_gpu_instance_config, H100_80GB, LLAMA_70B
import json


def run_comparison():
    """Run both stateful and stateless simulations."""

    # Setup: H100 with Llama-70B
    instances_config = [
        create_gpu_instance_config("gpu0", H100_80GB, LLAMA_70B),
        create_gpu_instance_config("gpu1", H100_80GB, LLAMA_70B),
    ]

    # RAG workload: 100 req/sec, 40% retrieval overlap
    def make_workload():
        return RAGWorkload(
            arrival_rate_requests_per_sec=100.0,
            system_prompt_tokens=512,
            retrieval_context_tokens=2048,
            user_query_tokens=128,
            retrieval_reuse_probability=0.4,
            output_tokens_mean=256,
            kv_cache_bytes_per_token=LLAMA_70B.kv_cache_bytes_per_token,
            seed=42,
        )

    print("=" * 70)
    print("Stateful vs Stateless Routing Comparison (RAG Workload)")
    print("=" * 70)
    print(f"\nSetup:")
    print(f"  - 2x H100 with Llama-70B")
    print(f"  - RAG workload: 100 req/sec, 40% retrieval overlap")
    print(f"  - Simulation: 30 seconds")
    print()

    # Run stateful (prefix-aware)
    print("Running STATEFUL (prefix-aware) router...")
    sim_stateful = EventDrivenSimulation(
        workload_gen=make_workload(),
        instances_config=instances_config,
        heartbeat_interval_ms=100.0,
        stateful=True,
    )
    sim_stateful.run(simulation_time_ms=30000.0)
    metrics_stateful = sim_stateful.get_metrics_summary()

    # Run stateless
    print("Running STATELESS (round-robin) router...")
    sim_stateless = EventDrivenSimulation(
        workload_gen=make_workload(),
        instances_config=instances_config,
        heartbeat_interval_ms=100.0,
        stateful=False,
    )
    sim_stateless.run(simulation_time_ms=30000.0)
    metrics_stateless = sim_stateless.get_metrics_summary()

    # Display results
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    print(f"\nRequests:")
    print(f"  Stateful:  {metrics_stateful['num_requests']:>5} generated, {metrics_stateful['completed_requests']:>5} completed")
    print(f"  Stateless: {metrics_stateless['num_requests']:>5} generated, {metrics_stateless['completed_requests']:>5} completed")

    print(f"\nCache Hit Rate:")
    print(f"  Stateful:  {metrics_stateful['cache_hit_rate']:>6.1%}")
    print(f"  Stateless: {metrics_stateless['cache_hit_rate']:>6.1%}")

    if metrics_stateful["completed_requests"] > 0 and metrics_stateless["completed_requests"] > 0:
        e2e_sf = metrics_stateful["e2e_latency_ms"]
        e2e_sl = metrics_stateless["e2e_latency_ms"]
        ttft_sf = metrics_stateful["ttft_ms"]
        ttft_sl = metrics_stateless["ttft_ms"]

        print(f"\nEnd-to-End Latency (ms):")
        print(f"  Stateful  - avg: {e2e_sf['avg']:>7.1f}, p50: {e2e_sf['p50']:>7.1f}, p99: {e2e_sf['p99']:>7.1f}")
        print(f"  Stateless - avg: {e2e_sl['avg']:>7.1f}, p50: {e2e_sl['p50']:>7.1f}, p99: {e2e_sl['p99']:>7.1f}")

        print(f"\nTime-to-First-Token (ms):")
        print(f"  Stateful  - avg: {ttft_sf['avg']:>7.1f}, p50: {ttft_sf['p50']:>7.1f}, p99: {ttft_sf['p99']:>7.1f}")
        print(f"  Stateless - avg: {ttft_sl['avg']:>7.1f}, p50: {ttft_sl['p50']:>7.1f}, p99: {ttft_sl['p99']:>7.1f}")

        # Compute deltas
        print(f"\nStateful vs Stateless Delta:")
        e2e_delta = ((e2e_sf['avg'] - e2e_sl['avg']) / e2e_sl['avg']) * 100
        ttft_delta = ((ttft_sf['avg'] - ttft_sl['avg']) / ttft_sl['avg']) * 100
        print(f"  E2E latency:  {e2e_delta:+.1f}%")
        print(f"  TTFT latency: {ttft_delta:+.1f}%")

    print(f"\nInstance Telemetry (Stateful):")
    for iid, telemetry in metrics_stateful["instance_telemetry"].items():
        print(f"  {iid}: HBM {telemetry['hbm_utilization']:>5.1%}, blocks={telemetry['num_blocks']:>3}, ops={telemetry['operations_completed']:>4}")

    print(f"\nInstance Telemetry (Stateless):")
    for iid, telemetry in metrics_stateless["instance_telemetry"].items():
        print(f"  {iid}: HBM {telemetry['hbm_utilization']:>5.1%}, blocks={telemetry['num_blocks']:>3}, ops={telemetry['operations_completed']:>4}")

    # JSON summary
    print("\n" + "=" * 70)
    print("Summary (JSON)")
    print("=" * 70)
    summary = {
        "stateful": {
            "completed_requests": metrics_stateful["completed_requests"],
            "cache_hit_rate": f"{metrics_stateful['cache_hit_rate']:.1%}",
            "e2e_latency_avg_ms": round(metrics_stateful["e2e_latency_ms"]["avg"], 1),
            "ttft_avg_ms": round(metrics_stateful["ttft_ms"]["avg"], 1),
        },
        "stateless": {
            "completed_requests": metrics_stateless["completed_requests"],
            "cache_hit_rate": f"{metrics_stateless['cache_hit_rate']:.1%}",
            "e2e_latency_avg_ms": round(metrics_stateless["e2e_latency_ms"]["avg"], 1),
            "ttft_avg_ms": round(metrics_stateless["ttft_ms"]["avg"], 1),
        },
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    run_comparison()
