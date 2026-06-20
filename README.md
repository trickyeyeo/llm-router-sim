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

## Next Steps

1. **Simulation Loop Architecture** (`simulator/simulation_loop.py`)
   - Time-stepped executor: request arrival → routing → prefill → decode → completion
   - GPU backend model with realistic timings
   - NATS-style telemetry mock

2. **CUJ Scenarios** (`simulator/cuj_scenarios.py`)
   - RAG pipelines with retrieval overlap
   - Few-shot inference with shared examples
   - Multi-turn conversations
   - Mixed LLM/SLM workloads

3. **Router Routing Logic** (`router/router.py`)
   - Initial policy: sticky to cached instance, fallback to round-robin
   - Evolve with NATS telemetry: affinity + load shedding

4. **Metrics & Analysis** (`experiments/cuj_analysis.py`)
   - Measure latency (TTFT, e2e p50/p99)
   - Track cache hit rates
   - Plot throughput vs. cache locality
   - Compare stateless vs. prefix-aware routing
