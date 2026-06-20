"""
Multi-turn conversation comparison: stateful vs stateless routing.

Demonstrates TTFT improvements for later conversation turns with prefix-aware routing.
Tracks how cache hit rate climbs and TTFT decreases as conversation history grows.
"""

from simulator.simulation_loop import EventDrivenSimulation
from simulator.workload import MultiTurnWorkload
from simulator.constants import create_gpu_instance_config, H100_80GB, LLAMA_70B
from collections import defaultdict


def run_multi_turn_comparison():
    """Run stateful vs stateless on identical multi-turn workload."""

    # Identical config for both runs
    instances_config = [
        create_gpu_instance_config("gpu0", H100_80GB, LLAMA_70B),
        create_gpu_instance_config("gpu1", H100_80GB, LLAMA_70B),
    ]

    # Multi-turn workload: 5 sessions, 5 turns each, ~1 second between turns
    def make_workload():
        return MultiTurnWorkload(
            num_sessions=5,
            turns_per_session=5,
            turn_interval_ms=1000.0,  # ~1 second (agent think time)
            system_prompt_tokens=512,
            tokens_per_turn_q_and_a=384,  # ~128 q + 256 a
            user_query_tokens=128,
            output_tokens_mean=256,
            kv_cache_bytes_per_token=LLAMA_70B.kv_cache_bytes_per_token,
            seed=42,
        )

    # Simulate long enough for all turns to complete
    sim_time = 35_000.0  # 35 seconds (5 sessions * 5 turns * 1.5 sec spacing)

    # Run stateful (prefix-aware)
    print("=" * 80)
    print("STATEFUL (prefix-aware) routing - Multi-turn conversations")
    print("=" * 80)
    sim_stateful = EventDrivenSimulation(
        workload_gen=make_workload(),
        instances_config=instances_config,
        heartbeat_interval_ms=100.0,
        stateful=True,
    )
    sim_stateful.run(sim_time)
    metrics_stateful = sim_stateful.get_metrics_summary()
    turns_stateful = _extract_turn_metrics(sim_stateful)

    # Run stateless (round-robin only)
    print("\n" + "=" * 80)
    print("STATELESS (round-robin) routing - Multi-turn conversations")
    print("=" * 80)
    sim_stateless = EventDrivenSimulation(
        workload_gen=make_workload(),
        instances_config=instances_config,
        heartbeat_interval_ms=100.0,
        stateful=False,
    )
    sim_stateless.run(sim_time)
    metrics_stateless = sim_stateless.get_metrics_summary()
    turns_stateless = _extract_turn_metrics(sim_stateless)

    # Print results
    print("\n" + "=" * 80)
    print("MULTI-TURN COMPARISON RESULTS")
    print("=" * 80)

    print(f"\nConfiguration:")
    print(f"  Sessions: 5")
    print(f"  Turns per session: 5")
    print(f"  Turn interval: 1000ms (agent think time)")
    print(f"  Total requests: 25")

    print(f"\nRequests Generated: {metrics_stateful['num_requests']}")
    print(f"Requests Completed: {metrics_stateful['completed_requests']}")

    # Overall metrics
    print(f"\n{'Metric':<30} {'Stateless':<20} {'Stateful':<20} {'Improvement'}")
    print("-" * 80)

    # Cache hit rate
    hit_rate_stateless = metrics_stateless.get("cache_hit_rate", 0.0)
    hit_rate_stateful = metrics_stateful.get("cache_hit_rate", 0.0)
    print(
        f"{'Cache Hit Rate':<30} {hit_rate_stateless:>18.1%}  {hit_rate_stateful:>18.1%}  "
        f"{((hit_rate_stateful - hit_rate_stateless) / max(hit_rate_stateless, 0.001)):>10.1%}"
    )

    # E2E latency
    e2e_stateless = metrics_stateless["e2e_latency_ms"]["avg"]
    e2e_stateful = metrics_stateful["e2e_latency_ms"]["avg"]
    e2e_improvement = ((e2e_stateless - e2e_stateful) / e2e_stateless) * 100 if e2e_stateless > 0 else 0
    print(f"{'E2E Latency (avg, ms)':<30} {e2e_stateless:>18.1f}  {e2e_stateful:>18.1f}  {e2e_improvement:>10.1f}%")

    # TTFT
    ttft_stateless = metrics_stateless["ttft_ms"]["avg"]
    ttft_stateful = metrics_stateful["ttft_ms"]["avg"]
    ttft_improvement = ((ttft_stateless - ttft_stateful) / ttft_stateless) * 100 if ttft_stateless > 0 else 0
    print(f"{'TTFT (avg, ms)':<30} {ttft_stateless:>18.1f}  {ttft_stateful:>18.1f}  {ttft_improvement:>10.1f}%")

    # TTFT P99
    ttft_p99_stateless = metrics_stateless["ttft_ms"]["p99"]
    ttft_p99_stateful = metrics_stateful["ttft_ms"]["p99"]
    ttft_p99_improvement = ((ttft_p99_stateless - ttft_p99_stateful) / ttft_p99_stateless) * 100 if ttft_p99_stateless > 0 else 0
    print(f"{'TTFT p99 (ms)':<30} {ttft_p99_stateless:>18.1f}  {ttft_p99_stateful:>18.1f}  {ttft_p99_improvement:>10.1f}%")

    # Per-turn breakdown (stateful)
    print(f"\n" + "=" * 80)
    print("STATEFUL: TTFT by Turn (shows cache benefits as history grows)")
    print("=" * 80)
    print(f"{'Turn':<8} {'Avg TTFT (ms)':<20} {'Cache Hit Rate':<20} {'Num Requests'}")
    print("-" * 80)
    for turn in sorted(turns_stateful.keys()):
        turn_data = turns_stateful[turn]
        print(
            f"{turn:<8} {turn_data['avg_ttft']:>18.1f}  {turn_data['cache_hit_rate']:>18.1%}  "
            f"{turn_data['count']:>12}"
        )

    # Per-turn breakdown (stateless)
    print(f"\n" + "=" * 80)
    print("STATELESS: TTFT by Turn (no cache benefit, flat across turns)")
    print("=" * 80)
    print(f"{'Turn':<8} {'Avg TTFT (ms)':<20} {'Cache Hit Rate':<20} {'Num Requests'}")
    print("-" * 80)
    for turn in sorted(turns_stateless.keys()):
        turn_data = turns_stateless[turn]
        print(
            f"{turn:<8} {turn_data['avg_ttft']:>18.1f}  {turn_data['cache_hit_rate']:>18.1%}  "
            f"{turn_data['count']:>12}"
        )

    # Per-turn TTFT improvement
    print(f"\n" + "=" * 80)
    print("TTFT Improvement by Turn (Stateful vs Stateless)")
    print("=" * 80)
    print(f"{'Turn':<8} {'Stateless (ms)':<20} {'Stateful (ms)':<20} {'Improvement'}")
    print("-" * 80)
    for turn in sorted(turns_stateful.keys()):
        stateless_ttft = turns_stateless.get(turn, {}).get("avg_ttft", 0)
        stateful_ttft = turns_stateful[turn]["avg_ttft"]
        if stateless_ttft > 0:
            improvement = ((stateless_ttft - stateful_ttft) / stateless_ttft) * 100
        else:
            improvement = 0
        print(f"{turn:<8} {stateless_ttft:>18.1f}  {stateful_ttft:>18.1f}  {improvement:>10.1f}%")


def _extract_turn_metrics(sim):
    """Extract TTFT and cache hit rate metrics by turn number."""
    turn_metrics = defaultdict(lambda: {"ttfts": [], "cache_hits": []})

    for req_id, metrics in sim.request_metrics.items():
        # Extract turn number from request_id (format: req_N)
        try:
            # For multi-turn, we need to infer turn from timing or request structure
            # Simple heuristic: turn number = ceil(request_index / num_sessions)
            # But we don't have that info easily. Instead, group by TTFT patterns.
            # Actually, let's extract from request_id pattern if available.
            # For now, use a simpler approach: requests arrive in turn order

            # Get corresponding routing decision
            cache_hit = False
            for decision in sim.routing_decisions:
                if decision.request_id == req_id:
                    cache_hit = decision.cache_hit
                    break

            if metrics.ttft_ms is not None:
                # Infer turn number: requests are ordered, 5 sessions * 5 turns = 25 total
                # Estimate: turn ≈ ceil(index / 5) for 5 sessions
                # This is approximate; a better approach would track turn in the request itself
                # For now, use sorted order to estimate turn
                pass
        except:
            pass

    # More robust: extract turn from the workload pattern
    # Requests should be grouped by turn: first 5 requests are turn 1 from each session, etc.
    completed_requests = [
        (req_id, m) for req_id, m in sim.request_metrics.items()
        if m.decode_complete_time is not None
    ]
    completed_requests.sort(key=lambda x: x[1].arrival_time)

    # Group into turns
    num_sessions = 5
    for idx, (req_id, metrics) in enumerate(completed_requests):
        turn_number = (idx % num_sessions) + 1  # 1-indexed

        # Find corresponding routing decision
        cache_hit = False
        for decision in sim.routing_decisions:
            if decision.request_id == req_id:
                cache_hit = decision.cache_hit
                break

        if metrics.ttft_ms is not None:
            turn_metrics[turn_number]["ttfts"].append(metrics.ttft_ms)
            turn_metrics[turn_number]["cache_hits"].append(cache_hit)

    # Aggregate
    result = {}
    for turn, data in turn_metrics.items():
        if data["ttfts"]:
            result[turn] = {
                "avg_ttft": sum(data["ttfts"]) / len(data["ttfts"]),
                "cache_hit_rate": sum(data["cache_hits"]) / len(data["cache_hits"]),
                "count": len(data["ttfts"]),
            }

    return result


if __name__ == "__main__":
    run_multi_turn_comparison()
