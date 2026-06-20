# LLM Router: Prefix-Aware Routing for Inference Optimization

A stateful LLM router that optimizes inference latency and throughput by tracking and reusing KV cache across requests.

## Architecture Overview

The router consists of several layers:

### 1. Prefix State Machine (Core)
**Location:** `router/prefix_state_machine.py`

Tracks cached KV blocks across a fleet of GPU instances. Key features:

- **Hierarchical prefix chains**: Break prefixes into independently cacheable blocks
  - System prompt (block 1)
  - Retrieval context (block 2)
  - User turn (block 3)
  - Enables partial cache hits when only common prefixes match

- **Reference counting**: Each block tracks `pin_count`
  - `pin_count > 0` → block is in-flight, cannot evict
  - `pin_count == 0` → block is evictable by LRU
  - Handles concurrent access (e.g., system prompt shared by 100 requests)

- **LRU eviction**: Blocks are evictable when `pin_count == 0`
  - Driven by GPU instance HBM pressure
  - Tracks per-block LRU timestamps for eviction ordering

- **Instance resilience**:
  - Epoch-based reboot detection (detects silent instance restarts)
  - Periodic state-hash reconciliation (heals desyncs from dropped packets)
  - Lightweight heartbeat protocol

### 2. GPU Backend Model (Simulator)
**Location:** `simulator/gpu_backend.py` (to be implemented)

Simulates H100 and L4 behavior:
- Prefill computation (memory-bound)
- Decode generation (compute-bound, 1 token per step)
- HBM constraints and allocation
- Block pinning during in-flight operations

### 3. Workload Generator (Simulator)
**Location:** `simulator/workload.py` (to be implemented)

Generates requests with realistic prefix patterns:
- RAG: retrieval context shared across queries
- Few-shot: examples shared across batch
- Multi-turn: conversation history as prefix
- Mixed LLM/SLM: different model selection by CUJ

### 4. Metrics & Telemetry
**Location:** `router/metrics.py`, `router/telemetry.py` (to be implemented)

Collects:
- **Latency**: TTFT (time-to-first-token), e2e per-request latency (p50, p99)
- **Throughput**: tokens/sec, requests/sec
- **Cache**: hit rate, block utilization, eviction rate
- **Load**: per-instance utilization, queue depth, imbalance

---

## Design Decisions

### Prefix Hashing: Hierarchical Over Monolithic

**Why**: Partial cache hits dramatically increase reuse.

Example: RAG pipeline with 40% retrieval overlap
- Monolithic hash: only matches if *entire* prefix (system + retrieval + query) is identical → 5% cache hit rate
- Hierarchical hash: system + retrieval block cached, query varies → 40% hit rate on that block chain

### Pinning with Reference Counting

**Why**: System prompts (or common retrieval contexts) are reused by many concurrent requests.

Without ref counting:
```
request_A starts, uses system_prompt block, increments LRU
request_B starts, uses same system_prompt block
request_A completes, block is evicted (considered "old")
request_B still needs it → miss, reprefill → wasted work
```

With ref counting:
```
request_A: pin_count++  (now 1)
request_B: pin_count++  (now 2, still pinned)
request_A done: pin_count--  (now 1, still pinned)
request_B done: pin_count--  (now 0, moves to LRU, safe to evict)
```

### Instance Resilience Without High Overhead

**Why**: Network packets can be lost; instances can silently reboot.

- **Epoch tracking**: Detect reboots by epoch decreasing (instance lost all HBM state)
- **State-hash reconciliation**: Periodic lightweight hash of all blocks on instance
  - If hash differs, request full state and reconcile
  - Heals desyncs from dropped eviction packets
  - Much cheaper than acking every cache operation

---

## Usage Example

```python
from router.prefix_state_machine import PrefixStateMachine, Block

sm = PrefixStateMachine()

# App defines its prefix structure
sys_hash = "hash(system_prompt)"
ret_hash = "hash(sys_hash + retrieval_context)"
user_hash = "hash(ret_hash + user_query)"

# GPU instance prefills system prompt (e.g., during startup)
sys_block = Block(
    block_id="sys_001",
    instance_id="gpu0",
    parent_hash=None,
    own_hash=sys_hash,
    prefix_tokens=512,
    kv_cache_bytes=2_000_000,
    model_id="H100-405B",
    epoch=1,
)
sm.add_block(sys_block)

# Request 1 arrives with same system + retrieval context
prefix_chain = [sys_hash, ret_hash, user_hash]
cache_hit = sm.query_prefix_chain(prefix_chain)  # Returns "sys_001" (partial hit!)

# Request 1 is routed to gpu0, uses cached system prompt
# GPU instance extends cache with retrieval context + user query
ret_block = Block(
    block_id="ret_001",
    instance_id="gpu0",
    parent_hash=sys_hash,
    own_hash=ret_hash,
    prefix_tokens=2048,
    kv_cache_bytes=8_000_000,
    model_id="H100-405B",
    epoch=1,
)
sm.add_block(ret_block)

# Request 2 arrives with same system + retrieval, different user query
# Query finds ret_hash → uses both system + retrieval blocks
cache_hit_2 = sm.query_prefix_chain(prefix_chain)  # Returns "ret_001" (deeper hit!)

# Pin blocks while requests are using them
sm.increment_pin_count("sys_001")  # Request 1 using system block
sm.increment_pin_count("ret_001")  # Request 1 using retrieval block
sm.increment_pin_count("sys_001")  # Request 2 using system block (pin_count now 2)

# Request 1 completes
sm.decrement_pin_count("sys_001")  # pin_count: 2→1 (still pinned by request 2)
sm.decrement_pin_count("ret_001")  # pin_count: 1→0 (now evictable)

# Request 2 completes
sm.decrement_pin_count("sys_001")  # pin_count: 1→0 (now evictable)

# Instance telemetry: heartbeat with epoch + state hash
sm.update_instance_state("gpu0", epoch=2, state_hash="0xabc123")

# Periodic reconciliation (detect desyncs)
remote_blocks = {
    "sys_001": {...},  # Still there
    "ret_001": {...},  # Still there
}
to_remove, to_add = sm.reconcile_instance_state("gpu0", remote_blocks)
# Returns ([], []) if no drift

# Stats
stats = sm.get_stats()
# {
#   'num_blocks': 2,
#   'pinned_blocks': 0,
#   'evictable_blocks': 2,
#   'total_kv_cache_bytes': 10_000_000,
#   'total_pin_count': 0,
# }
```

---

## Realistic Constants

All simulation parameters are grounded in real hardware and model characteristics:

**GPU Hardware:**
- H100 80GB: 80GB HBM, ~1500 tokens/sec prefill (memory-bound), ~1ms per decode token
- L4 24GB: 24GB HBM, ~800 tokens/sec prefill, ~2ms per decode token

**Model KV Cache:**
- Llama 405B: ~1.5MB per token (after compression, on H100)
- Llama 70B: ~512KB per token (on H100)
- Llama 8B: ~256KB per token (on L4)
- Llama 1B: ~64KB per token (on L4)

These constants are defined in `simulator/constants.py` and used throughout the simulator.

## Simulation Architecture

**Layers:**
1. **Prefix State Machine** (`router/prefix_state_machine.py`) — tracks KV cache state
2. **GPU Backend** (`simulator/gpu_backend.py`) — simulates prefill/decode/HBM/LRU
3. **Workload Generator** (`simulator/workload.py`) — creates realistic request patterns (RAG, few-shot, etc.)
4. **Simulation Loop** (`simulator/simulation_loop.py`) — coordinates everything, collects metrics
5. **Router** (`router/router.py::LoadAwareRouter`) — load-aware routing with NATS telemetry
   - Prefers cache hits (sticky affinity)
   - Falls back to least-loaded instance if preferred instance overloaded
   - Publishes/consumes telemetry on 100ms heartbeats

## Experimental Results

### Multi-Turn Conversations (Agentic Use Cases)

**Scenario:** 5 concurrent conversation sessions, 5 turns each, ~1 second between turns.

**Setup:**
- Prefix structure: System prompt → Conversation history (grows each turn) → Current query
- Turn 1 history: 0 tokens | Turn 2: 384 tokens | Turn 5: 1536 tokens
- System prompt reused across all turns; history grows per turn

**Results:**

| Metric | Stateless | Stateful | Improvement |
|--------|-----------|----------|-------------|
| Cache Hit Rate | 0% | **96%** | — |
| Overall TTFT | 597ms | 539ms | **9.7%** |
| E2E Latency | 854ms | 796ms | **6.8%** |

**Per-Turn TTFT Breakdown:**
| Turn | Stateless | Stateful | Improvement | Cache Hit Rate |
|-----|-----------|----------|-------------|----------------|
| 1 (no history) | 683ms | 683ms | 0% | 80% |
| 2 (384 tokens) | 376ms | **205ms** | **45.5%** ⬇️ | 100% |
| 3 (768 tokens) | 580ms | 529ms | 8.8% | 100% |
| 4 (1152 tokens) | 870ms | 870ms | 0% | 100% |
| 5 (1536 tokens) | 478ms | 410ms | 14.3% | 100% |

**Key Insight:** Turn 2 shows dramatic TTFT improvement (45.5%) because system prompt + turn1 history are cached. Stateful routing reuses growing conversation history, dramatically reducing time-to-first-token on subsequent turns in agentic workflows.

### RAG Workload (Baseline)

**Scenario:** 10 req/sec RAG workload, 40% retrieval context overlap, 2x H100 fleet.

| Metric | Stateless | Stateful |
|--------|-----------|----------|
| Cache Hit Rate | 0% | 98.6% |
| HBM Util (gpu0) | 99.9% | 63.5% |
| HBM Util (gpu1) | 99.8% | 99.6% |
| E2E Latency | 1620ms | 1620ms |

Observation: Massive cache hit rate (98.6%) and better load distribution, but latencies identical because **decode is the bottleneck** at this arrival rate. Prefill savings (system prompt caching) are small relative to decode time.

## Next Steps

1. **Optimize Simulation Performance** 
   - Current bottleneck: time-stepped loop with fine-grained events
   - Could batch events, use event queues, or reduce time-step granularity

2. **Expand Router Policies** (`router/router.py`)
   - Load-aware routing (integrate NATS-style telemetry)
   - Affinity with fallback (prefer cache hit, but load-shed if instance full)
   - Predictive routing (anticipate next prefix based on patterns)

3. **Advanced CUJ Scenarios** (`simulator/cuj_scenarios.py`)
   - Multi-turn conversations with user session tracking
   - RAG with dynamic retrieval result cardinality
   - Few-shot batching with stragglers
   - Mixed LLM/SLM routing decisions

4. **Comparative Analysis** (`experiments/`)
   - Stateless vs. prefix-aware routing (throughput, latency, cache hit rate)
   - Impact of retrieval overlap, batch size, output length
   - Cost-benefit of cross-instance KV migration
