"""
Basic RAG experiment: demonstrate prefix-aware routing in action.

Simulates RAG workload with shared retrieval context.
Compares performance with 40% retrieval overlap.
"""

from simulator.simulation_loop import SimulationLoop
from simulator.workload import RAGWorkload
from simulator.gpu_backend import GPUInstanceConfig
import json


def run_rag_experiment():
    """Run basic RAG experiment."""

    # Configure GPU instances
    instances_config = [
        GPUInstanceConfig(
            instance_id="gpu0",
            model_id="H100-405B",
            hbm_capacity_bytes=80 * 1024 * 1024 * 1024,  # 80 GB
            prefill_throughput_tokens_per_ms=500.0,  # 500 tokens/ms
            decode_latency_per_token_ms=1.0,  # 1ms per token
        ),
        GPUInstanceConfig(
            instance_id="gpu1",
            model_id="H100-405B",
            hbm_capacity_bytes=80 * 1024 * 1024 * 1024,  # 80 GB
            prefill_throughput_tokens_per_ms=500.0,
            decode_latency_per_token_ms=1.0,
        ),
    ]

    # Configure workload: RAG with 40% retrieval overlap
    workload = RAGWorkload(
        arrival_rate_requests_per_sec=100.0,  # 100 requests/sec
        system_prompt_tokens=512,
        retrieval_context_tokens=2048,
        user_query_tokens=128,
        retrieval_reuse_probability=0.4,  # 40% reuse
        output_tokens_mean=256,
        seed=42,
    )

    # Create and run simulation
    sim = SimulationLoop(
        workload_gen=workload,
        instances_config=instances_config,
        heartbeat_interval_ms=100.0,
        time_step_ms=1.0,
    )

    print("Running RAG experiment for 10 seconds...")
    sim.run(simulation_time_ms=10000.0)

    # Collect metrics
    metrics = sim.get_metrics_summary()

    print("\n" + "=" * 60)
    print("RAG Experiment Results")
    print("=" * 60)
    print(f"Requests generated: {metrics['num_requests']}")
    print(f"Requests completed: {metrics['completed_requests']}")
    print(f"Cache hit rate: {metrics['cache_hit_rate']:.2%}")

    if metrics["e2e_latency_ms"]:
        e2e = metrics["e2e_latency_ms"]
        print(f"\nEnd-to-end latency (ms):")
        print(f"  Min: {e2e['min']:.2f}")
        print(f"  Avg: {e2e['avg']:.2f}")
        print(f"  P50: {e2e['p50']:.2f}")
        print(f"  P99: {e2e['p99']:.2f}")
        print(f"  Max: {e2e['max']:.2f}")

    if metrics["ttft_ms"]:
        ttft = metrics["ttft_ms"]
        print(f"\nTime-to-first-token (ms):")
        print(f"  Min: {ttft['min']:.2f}")
        print(f"  Avg: {ttft['avg']:.2f}")
        print(f"  P50: {ttft['p50']:.2f}")
        print(f"  P99: {ttft['p99']:.2f}")
        print(f"  Max: {ttft['max']:.2f}")

    print(f"\nInstance telemetry:")
    for iid, telemetry in metrics["instance_telemetry"].items():
        print(f"  {iid}:")
        print(f"    HBM utilization: {telemetry['hbm_utilization']:.2%}")
        print(f"    Blocks cached: {telemetry['num_blocks']}")
        print(f"    Pinned blocks: {telemetry['num_pinned_blocks']}")
        print(f"    Operations completed: {telemetry['operations_completed']}")

    # Print summary for easy copy-paste
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(json.dumps(
        {
            "cache_hit_rate": f"{metrics['cache_hit_rate']:.2%}",
            "e2e_latency_p50_ms": f"{metrics['e2e_latency_ms']['p50']:.2f}",
            "e2e_latency_p99_ms": f"{metrics['e2e_latency_ms']['p99']:.2f}",
            "ttft_p50_ms": f"{metrics['ttft_ms']['p50']:.2f}",
            "ttft_p99_ms": f"{metrics['ttft_ms']['p99']:.2f}",
        },
        indent=2,
    ))


if __name__ == "__main__":
    run_rag_experiment()
