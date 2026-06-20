# LLM Router: Prefix-Aware Routing & Graceful Degradation

## What Makes This Interesting

Modern distributed LLM clusters are built on stateless load balancers. By scattering consecutive turns of the same conversation across different physical GPUs, we force the hardware to repeatedly recompute identical conversation history (prefill) on every single turn.  This creates a massive, invisible operational bottleneck:
* UX Degradation: Users experience frustrating, compounding response lag (TTFT) as conversation histories grow.
* Financial Waste: Up to 40% of precious GPU compute cycles are wasted doing repetitive recalculations of data we already computed.

In this llm-router sim, we implement some of the key building blocks for stateful LLM-aware routing. Here are some of the key design decisions & tradeoffs


* **NATs-based Telemetry**: We have an independent pubsub control stream of health and capacity metrics to decentralize routing decisions.
* **Scoring over binary thresholds**: We have continuous ranking prevents thundering herd better than "route to GPU if <80% HBM".
* **On-demand P2P transfers**: Recovery happens lazily when needed, not preemptively. 
* **LLM vs SLM**: We introduce the possibility of routing to SLMs to minimize cost on heavier newer hardware (missing from the demo).
* **Separate prefill/decode queue tracking**: In scoring, we separate prefill from decode due to stark differences in cost.
* **Cache concentration, not spreading**: Routing to cache owner maximizes reuse and throughput. 

### 1. Cache-Aware Load Balancing (Not Just Utilization)

Most load balancers route on queue depth or HBM utilization. This router knows **what's cached** and trades off cache value against queue penalties via a continuous scoring function:

```
score = (matched_tokens / total_tokens) × prefill_time_saved × w_cache
        - (prefill_queue_depth × 5 + decode_queue_depth × 1 + hbm_utilization × 3)
        + noise
```

This means a GPU with a cache hit stays preferred even if slightly loaded—**unlocking 2.5x+ capacity gains** instead of distributing randomly. The key insight: cache concentration is preferable to queue concentration. When you route 50 sessions to the GPU that cached their shared system prompt, you get 99% hit rates and massive throughput. When you distribute round-robin "fairly," you get 0% hits and cascade failures.

### 2. Graceful Degradation via P2P KV Transfers

When a GPU fails, rather than losing all cached state and forcing full prefills, the system **recovers by transferring KV cache blocks peer-to-peer** (RDMA 100Gbps or TCP fallback). This keeps latency impact **~5-10% even with 20% failure rate**, vs. cascading failure modes that would spike latency 50%+ or cause queue collapse.

The design accepts that transfers may timeout → fallback to prefill from scratch. No complex partial recovery logic—just on-demand transfers with a fallback path.

### 3. Network-Aware Transfer Strategy

RDMA vs TCP isn't a "pick once" decision—it's surfaced as a **tunable parameter in routing**. This makes visible the 10x latency difference (10-15ms vs 100-150ms) and justifies infrastructure investment in high-speed interconnects. In production, you'd want to measure: do the transfer time savings justify the RDMA NIC cost? This demo lets you see both sides.


## Architecture Layers

**Routing Layer** (`router/router.py`)
- Computes cache value from matched token ratio
- Applies load penalty scaling (prefill >> decode)
- Tie-breaks on noise to avoid pure cache affinity when load is extreme

**Failure Management** (`simulator/gpu_backend.py`)
- Tracks health status (HEALTHY / DEGRADED / FAILED)
- Epoch-based recovery: check if recovery_deadline has passed
- No explicit cascade; failures appear as cache misses to router

**Transfer Coordination** (`router/prefix_state_machine.py`)
- Tracks in-flight P2P transfers (from → to GPU, block_id, start_time)
- Completes or fails transfers; failed → cascades to cache miss
- Integrates with simulation event loop for deterministic replay

**Demo UI** (React + Recharts)
- Two pre-canned scenarios: Caching Affinity (50 sessions, capacity story) and Graceful Degradation (20 sessions, resilience story)
- Comparison mode dynamically updates Expert accordion metrics
- Multiple API calls for dual-run demos (baseline vs with P2P)

## Simulation Realism

The simulator includes:
- **Multi-turn conversation workload** with turn_interval_ms (realistic think time)
- **Hierarchical prefix hashing** matching system_prompt → history1 → history2 → query
- **Per-GPU LRU eviction** when HBM fills
- **Block-level granularity** for transfers (not whole-conversation)
- **Staggered session arrivals** (50 sessions arriving over ~1.5min, not all at once)

One gap: **No contention modeling for network links** (assumes infinite bisection bandwidth). Real deployments would see bandwidth saturation with many concurrent transfers, affecting transfer time estimates.

## What's Not Obvious (Non-Obvious Aspects)

1. **Cache concentration is a feature, not a bug.** The demo shows GPU1 with 0 blocks in stateful mode—this isn't a thundering herd problem, it's correct behavior. All 50 sessions found their shared system prompt on GPU0 and stayed there. Stateless round-robin spreads load "fairly" but gets 0% cache hits. The throughput win (2.8x) comes from affinity, not distribution.

2. **Scoring prevents queue collapse, not load balance.** If you route 50 requests without cache to two idle GPUs, round-robin spreads them. But if one GPU fills up (high prefill_queue), subsequent requests prefer the lighter one *even if it has no cache*. This prevents queue explosion. Scoring trades these two forces dynamically.

3. **P2P transfer time (10-15ms) is always faster than prefill (500ms).** So even a ~2% timeout rate on transfers is worth it—you still save 98% of prefill costs. The fallback to prefill-from-scratch is a safety valve, not the common path.

4. **Separate queue tracking is subtle but essential.** Prefill requests block a GPU for 500ms; decode requests for 50-100ms. Penalizing them equally (same weight) would make prefill-heavy systems prefer light decode queues, losing cache affinity. By weighting prefill 5x heavier, the scoring correctly biases toward cache owner even if it's processing a prefill.

## How I'd Extend This With More Time (Read me!)

- **Heterogeneous GPU pools**: H100s for prefill, L4s for decode; route by compute affinity and cache ownership. We planned on doing this but ran out of time.
- **Add LoRA models and load times**: Specialized models (LoRA) often take up HBM space in real world scenarios and incorporating this in the routing layer (cost of swaps) would be interesting.
- **Multi-cluster routing** (or even multi cloud routing). Capacity is scarce and reliability over multiple cloud provides can vary. Having a layer-1 router that can make some of these decisions should be able to sit atop this current design.
- **Incorporating TPUs** TPUs have slightly different constraints in how they fit blocks, but have enormous bisection bandwidth between them.

### Suggestions from Claude (with some annation).
- **Predictive prefilling**: Anticipate next turns and pre-stage cache before request arrival (this seems too speculative within an assignment, but nice as a followup).
- **Transfer batching & priorities**: Coalesce small KV transfers; prioritize critical sessions over best-effort (yes).
- **Network simulation**: Model link saturation and contention for P2P transfers, affecting transfer time estimates (this is less intersting, we already have a large diff between TCP and RDMA).
- **Failure prediction**: Use GPU telemetry (thermal, power) to predict failures before they occur, proactive recovery (We have some smart versioning in NATs but the problem is "who watches the watcher").
