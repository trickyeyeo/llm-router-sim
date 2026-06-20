# GPU Failure Handling & Scoring-Based Routing Architecture

## Overview

Extended the LLM Router with:
1. **Scoring-based routing** to prevent thundering herds by trading off cache value vs load
2. **Separate queue tracking** (prefill vs decode) for accurate latency modeling  
3. **GPU failure resilience** with P2P KV block transfer capabilities
4. **Health-aware routing** that gracefully degrades when instances fail

This document outlines Phases 1-2 (complete) and Phase 3 stubs (ready for implementation).

---

## Phase 1: Foundation (Constants & State Machine)

### Network Configuration

**New in `simulator/constants.py`:**
- `NetworkConfig` dataclass defining network bandwidth
- `NETWORK_RDMA`: 100 Gbps = 12,500 bytes/ms (P2P transfers via RoCE)
- `NETWORK_TCP`: 10 Gbps = 1,250 bytes/ms (fallback for non-RDMA hardware)
- Updated `GPUConfig` with `network_type` field (defaults to "rdma")

### Routing Weights Configuration

**New in `simulator/constants.py` - `RoutingWeights` & defaults:**
```python
w_cache = 1.0              # Cache value multiplier
w_prefill_queue = 0.5      # Per prefill request penalty (5-10s latency)
w_decode_queue = 0.1       # Per decode request penalty (100ms latency)
w_hbm = 3.0                # HBM utilization penalty (soft, not binary)
noise_epsilon = 1.0        # Tie-breaking threshold
noise_magnitude = 0.5      # Max random noise
```

These weights are tuned to prefer cache but not at the cost of overwhelming queue congestion.

### Extended Telemetry

**New in `router/router.py` - `InstanceTelemetry`:**
```python
health_status: str = "healthy"        # "healthy" | "degraded" | "failed"
failure_reason: Optional[str] = None  # Reason for degraded/failed state
network_type: str = "rdma"            # Network capability for P2P transfers
prefill_queue_depth: int = 0          # Requests waiting for prefill (expensive)
decode_queue_depth: int = 0           # Requests in active decode (cheap)
```

Separate queue tracking allows different penalties based on actual latency impact:
- Prefill (5-10s) is 50x more expensive than decode (100ms)

### Transfer State Machine

**New in `router/prefix_state_machine.py`:**
- `TransferState` dataclass for P2P KV block transfers
- `PrefixStateMachine.transfers` dict tracking in-flight transfers
- Methods: `initiate_transfer()`, `complete_transfer()`, `fail_transfer()`, `get_transfers_in_flight()`
- Updated stats to include transfer metrics

**Design decision:** Pin count does NOT prevent transfer (GPUDirect allows concurrent reads)

---

## Phase 2: Scoring-Based Router (Prevents Thundering Herds)

### Problem Statement

**Binary routing creates thundering herds:**
- Old logic: "If cache hit and HBM < 0.8, route there"
- Result: 5 requests arrive, all see cache on gpu0, all queue up (latency spike)

**Solution: Continuous scoring with load penalties**
- Route based on: cache_value - load_penalty
- High queue depth reduces attractiveness even if cache exists
- Distributes load across instances, trading some cache misses for better throughput

### Score Formula

```
score = cache_value - load_penalty + noise

cache_value = (matched_tokens / total_tokens) * prefill_time_saved * w_cache

load_penalty = prefill_queue_depth * w_prefill_queue
             + decode_queue_depth * w_decode_queue  
             + hbm_utilization * w_hbm

noise = random(-magnitude, +magnitude) if scores within epsilon else 0
```

### Routing Decision Algorithm

1. **Query cache** for matched_tokens on any instance
2. **Score all healthy instances**:
   - Calculate cache_value: how much time saved by reusing prefix
   - Calculate load_penalty: queue congestion + HBM utilization impact
   - Apply tie-breaking noise if scores are close
3. **Route to highest-scoring instance**
4. **Determine strategy**:
   - CACHE_HIT: if routing to instance with cached block
   - AFFINITY_DEGRADED: if cache exists but routing elsewhere for load
   - LOAD_BALANCED: if no cache, pure load distribution

### Example Scenarios

**Scenario A: Cache worth the wait**
```
GPU0: 256 tokens cached (256ms saved), 5 prefill queue, 10% HBM
      cache_value = (256/512) * 256 * 1.0 = 128
      load_penalty = 5*0.5 + 10%*3.0 = 2.8
      score = 128 - 2.8 = 125.2  <-- STRONG PREFERENCE

GPU1: No cache, 0 queue, 10% HBM
      cache_value = 0
      load_penalty = 0 + 10%*3.0 = 0.3
      score = 0 - 0.3 = -0.3

=> Route to GPU0 (cache hit)
```

**Scenario B: Cache overcome by congestion**
```
GPU0: 256 tokens cached (128), 150 prefill queue, 90% HBM
      load_penalty = 150*0.5 + 90%*3.0 = 77.7
      score = 128 - 77.7 = 50.3  <-- POSITIVE but marginal

GPU1: No cache, 0 queue, 5% HBM
      score = 0 - 0.15 = -0.15

=> Route to GPU0 (still prefer cache)

BUT if GPU0 reaches 200+ queue:
      load_penalty = 200*0.5 + 90%*3.0 = 102.7
      score = 128 - 102.7 = 25.3

GPU1 becomes comparable and noise might flip decision => LOAD_BALANCED
```

**Scenario C: Prefill vs decode distinction**
```
GPU0: No cache, 10 prefill queue (10*0.5 = 5), 5 decode queue (5*0.1 = 0.5)
      load_penalty = 5 + 0.5 = 5.5
      score = 0 - 5.5 = -5.5

GPU1: No cache, 0 prefill, 50 decode queue (50*0.1 = 5)
      load_penalty = 0 + 5 = 5
      score = 0 - 5 = -5

=> Route to GPU1 (lighter load)

Rationale: 10 prefill requests (50-100s total latency) worse than 50 decode requests (5s total)
```

### Separate Queue Tracking Benefits

By tracking prefill and decode queues separately:
- **Accurate load assessment**: Prefill-heavy GPUs are heavily penalized
- **Decode burst handling**: Can route more decode requests to already-busy GPUs  
- **Priority awareness**: Scheduler can prefer instances with low prefill queues
- **Better cache utilization**: Subtle load differences influence routing without binary cliffs

### Transfer Viability Evaluation

**New method: `evaluate_transfer_viability()`**
```python
transfer_time = block_size_bytes / network_bandwidth_bytes_per_ms
prefill_time = prefix_tokens / prefill_throughput_tokens_per_sec

should_transfer = transfer_time < prefill_time
```

Example:
- 512KB block, RDMA (12,500 B/ms): 512,000 / 12,500 = 41ms
- Prefill 256 tokens @ 1000 tok/sec: 256ms
- Result: Transfer is 6x faster, worth doing

### Health-Aware Routing

When an instance is degraded or failed:
1. Score only healthy instances
2. If no healthy instances, include all (graceful degradation)
3. Route to highest-scoring available instance
4. If cache exists but on unavailable instance → AFFINITY_DEGRADED strategy

---

## Phase 2 Extensions: Design Decisions

**A. Replication strategy:** On-demand transfers only
- Simpler implementation
- Reduces HBM overhead (no replicas)
- Can add proactive replication in Phase 3 if needed

**B. Transfer failure recovery:** Prefill from scratch
- Simple and robust
- Transfer failures rare (RDMA is reliable)
- Avoids complex rollback logic

**C. Cascade failures:** Treat as cache miss
- Preferred instance failed? Route to healthy instance
- If all healthy instances fail, route to any (last resort)
- Gracefully degrades under cascading failures

**D. Pin count constraint:** Removed
- GPUDirect P2P allows concurrent reads during transfer
- Source GPU streams block while destination reads cached data
- Pin count tracks "active decode" not "readable from cache"

---

## Phase 3: Failure Injection (Stubs Ready)

### Failure Injection Config

**New in `simulator/constants.py`:**
```python
@dataclass
class FailureInjectionConfig:
    enabled: bool = False
    failure_rate: float = 0.0             # Probability per request
    failure_detection_delay_ms: float = 100.0    # Heartbeat interval
    failure_recovery_time_ms: float = 5000.0     # Time to recover
    failure_type: str = "random"          # "random" | "cascading" | "periodic"
```

### FailureSimulator Stub

**New in `router/router.py`:**
- `should_inject_failure()`: Random failure generation
- `inject_failure()`: Record failure with timestamp
- `recover_instance()`: Schedule recovery
- `is_instance_failed()`: Check current status
- `get_failure_reason()`: Return details

**Planned Phase 3 implementation:**
1. Randomly inject failures at configured rate
2. Update InstanceTelemetry with health_status="failed" at heartbeat
3. Model detection latency (heartbeat interval)
4. Model recovery time (configurable duration)

---

## Test Coverage

**Test Suite Summary: 47 tests (all passing)**

1. **Prefix State Machine** (25 tests)
   - Block creation, pin counting, eviction
   - Hierarchical prefix chains
   - Instance tracking and reboot detection
   - State reconciliation

2. **Router Load Distribution** (5 tests)
   - Round-robin without cache
   - Sticky routing with cache
   - Affinity degradation under load
   - Least-loaded selection

3. **Scoring-Based Routing** (11 tests)
   - Cache value calculation (time saved weighting)
   - Load penalty (prefill > decode)
   - HBM penalty (soft threshold)
   - Score combination and tie-breaking
   - Thundering herd prevention
   - Load distribution

4. **Transfer Viability & Health-Aware Routing** (6 tests)
   - Transfer time vs prefill cost
   - Routing to healthy instances
   - Degradation paths
   - Transfer state tracking

---

## Metrics & Instrumentation

### Router-Level Metrics
- `transfers_initiated`: P2P transfers started
- `transfers_completed`: Successful transfers
- `transfers_failed`: Failed transfers
- `blocked_by_failure_count`: Requests hitting failed instance
- `recovered_by_transfer_count`: Requests that succeeded via transfer

### Per-Instance Metrics (from telemetry)
- `health_status`: Current state (health/degraded/failed)
- `prefill_queue_depth`: Requests awaiting prefill
- `decode_queue_depth`: Requests in active decode
- `hbm_utilization`: Memory pressure
- `num_cached_blocks`: Cache efficiency

### Scoring Metrics
- `cache_value`: Time saved by prefix cache
- `load_penalty`: Queue + HBM impact
- `routing_score`: Final score used for routing decision
- `tie_breaking_noise`: Random variance applied

---

## Trade-offs & Constraints

| Decision | Rationale | Alternative | Why Not |
|----------|-----------|-------------|---------|
| Scoring-based routing | Prevents thundering herds, soft thresholds | Binary routing | Creates cascades when one GPU gets popular |
| On-demand transfers | Simpler, lower overhead | Proactive replication | Adds complexity, wastes HBM on cold blocks |
| Prefill-from-scratch recovery | Robust, simple | Retry transfer | Complex state tracking, potential inconsistency |
| Separate queue tracking | Accurate latency modeling | Single queue | 50x latency difference not captured |
| GPUDirect P2P (no pin constraint) | Concurrent reads allowed | Pin count blocks transfer | Reduces transfer throughput, adds latency |

---

## Next Steps (Phase 3)

1. **Failure Injection Loop**
   - Integrate FailureSimulator into simulation event queue
   - Randomly trigger failures at configured rate
   - Update instance health_status in telemetry

2. **P2P Transfer Events**
   - Add `EventType.TRANSFER_COMPLETE` to event queue
   - Model transfer latency before block becomes usable on destination
   - Handle transfer failures with fallback to prefill

3. **GPU Backend Enhancements**
   - Track prefill vs decode queue separately
   - Update telemetry to include both queue depths
   - Model recovery time when instance comes back online

4. **Metrics & Visualization**
   - Expose transfer metrics in webapp
   - Add network type selector (TCP vs RDMA)
   - Add failure injection controls

5. **Testing**
   - Cascade failure scenarios
   - RDMA vs TCP performance comparison
   - Queue distribution under load
   - Cache hit rate with failures injected

---

## Architecture Validation

✅ **47 tests passing**
- Prefix state machine: 25/25
- Router distribution: 5/5
- Scoring-based routing: 11/11
- Transfer viability: 6/6

✅ **Backward compatible**
- health_status defaults to "healthy"
- Transfer tracking opt-in

✅ **Production-ready weights**
- Tuned to balance cache reuse vs load distribution
- Soft penalties (no binary cliffs)
- Tested against thundering herd scenarios

---

## Key Insights

1. **Queue type matters**: Prefill requests are 50-100x more expensive than decode
2. **Scoring prevents herds**: Continuous scoring naturally distributes load without explicit logic
3. **Tie-breaking noise helps**: When scores are similar, randomness prevents synchronized decisions
4. **Health status flows**: Telemetry → State Machine → Routing Decisions (no polling)
5. **GPUDirect enables concurrency**: Can transfer blocks while they're being read

