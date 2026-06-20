# LLM Router Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                             │
│  ParameterPanel │ GPUCards │ KeyMetrics │ ComparisonCharts │ Expert  │
└────────────────────────────┬────────────────────────────────────────┘
                             │ SSE Stream (Heartbeats)
                             │
┌────────────────────────────┴────────────────────────────────────────┐
│                    FASTAPI Backend (main.py)                         │
│  /simulate endpoint streams EventDrivenSimulation metrics to client  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────────────────┐
│                  EventDrivenSimulation (Orchestrator)                │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Event Queue (Priority Heap by time)                        │   │
│  │  ├─ ARRIVAL: Request arrives at simulation time            │   │
│  │  ├─ PREFILL_COMPLETE: Prefill operation done              │   │
│  │  ├─ DECODE_COMPLETE: Decode operation done                │   │
│  │  ├─ HEARTBEAT: Publish telemetry (every 100ms default)    │   │
│  │  ├─ TRANSFER_COMPLETE: P2P transfer done (Phase 3)        │   │
│  │  └─ FAILURE/RECOVERY: GPU state changes (Phase 3)         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                             │                                        │
│  ┌──────────────────────────┴─────────────────────────────────┐   │
│  │              Request Arrival Handler                       │   │
│  │  1. Get request from workload                             │   │
│  │  2. Call router.route(request) → RoutingDecision         │   │
│  │  3. Schedule prefill operations on chosen instance        │   │
│  │  4. Track request in active_requests                      │   │
│  └──────────────────────────────────────────────────────────┘    │
│                             │                                        │
└─────────────────────────────┼────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
   ┌─────────┐        ┌──────────────┐       ┌──────────────┐
   │  GPU0   │        │ GPU1         │ ◄──► │ GPU2 (etc.)  │
   │Instance │        │ Instance     │       │ Instance     │
   └─────────┘        └──────────────┘       └──────────────┘


## Routing Decision Flow (Scoring-Based)

```
Request Arrives
    │
    ▼
┌─────────────────────────────────┐
│ LoadAwareRouter.route()         │
│ (stateful or stateless)         │
└──────────────┬──────────────────┘
               │
               ▼
    ┌──────────────────────────┐
    │ Query Prefix Cache       │
    │ (PrefixStateMachine)     │
    │                          │
    │ query_prefix_chain(      │
    │   request.prefix_hashes  │
    │ )                        │
    └──────────┬───────────────┘
               │
         ┌─────┴──────┐
         │            │
    CACHE HIT    CACHE MISS
         │            │
         ▼            ▼
   ┌──────────┐  ┌──────────────┐
   │ Get block│  │ No cache hit │
   │ owner    │  │ Matched = 0  │
   │ instance │  └──────────────┘
   └────┬─────┘         │
        │               │
        └───────┬───────┘
                │
                ▼
    ┌───────────────────────────────┐
    │ Score All Instances           │
    │ For each GPU:                 │
    │   score = cache_value         │
    │         - load_penalty        │
    │         + noise (tie-break)   │
    └───────────────────────────────┘
                │
                ▼
    ┌───────────────────────────────┐
    │ Select Instance with Highest  │
    │ Score (with tie-breaking)     │
    │ → RoutingDecision             │
    └───────────────────────────────┘


## Scoring Components

┌─────────────────────────────────────────────────────────────────┐
│ CACHE VALUE CALCULATION                                         │
│                                                                 │
│ cache_value = (matched_tokens / total_tokens)                  │
│             × prefill_time_saved_ms                            │
│             × w_cache_weight                                   │
│                                                                 │
│ Only assigned to instance_id that OWNS the cached block        │
│ All other instances get cache_value = 0                        │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ LOAD PENALTY CALCULATION                                        │
│                                                                 │
│ load_penalty = (prefill_queue_depth × w_prefill)               │
│              + (decode_queue_depth × w_decode)                 │
│              + (hbm_utilization × w_hbm)                       │
│                                                                 │
│ Weights (hardcoded):                                            │
│   w_prefill = 0.5  (5x heavier than decode)                   │
│   w_decode = 0.1                                               │
│   w_hbm = 3.0      (soft scaling, not binary)                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ FINAL SCORE                                                     │
│                                                                 │
│ total_score = cache_value - load_penalty + noise               │
│                                                                 │
│ Noise tie-breaking:                                             │
│   If |score[i] - score[best]| <= noise_epsilon:                │
│     Add random noise ∈ [-noise_magnitude, +noise_magnitude]    │
│   Re-select highest scorer                                      │
│                                                                 │
│ Result: Requests distribute across GPUs when scores are close  │
│ (preventing thundering herd) while preferring cache owners     │
└─────────────────────────────────────────────────────────────────┘


## Telemetry & Heartbeat Flow (NATS-like Pub/Sub)

```
┌─────────────────────────────────────────────────────────┐
│ LoadAwareTelemetryBroker (centralized pub/sub)         │
│                                                         │
│ publish_telemetry(InstanceTelemetry)                   │
│   └─ Stores latest telemetry for each instance_id      │
│      (latest_telemetry dict)                           │
│                                                         │
│ get_instance_telemetry(instance_id)                    │
│   └─ Returns latest telemetry for routing decisions    │
└──────────┬──────────────────────────────────────────────┘
           │
           ▲
           │ Published every 100ms (default)
           │
    ┌──────┴──────────────────────────────┐
    │                                      │
┌───┴─────────────────┐      ┌────────────┴──────┐
│ Heartbeat Event     │      │ _send_heartbeats()│
│ (EventType.HB)      │      │ (called per event)│
│ Scheduled every     │      │                   │
│ heartbeat_interval_ │      │ For each GPU:     │
│ ms into event queue  │      │  get_telemetry() │
└─────────────────────┘      │  → InstanceTel   │
                              │  publish()       │
                              └──────────────────┘
                                     │
                                     ▼
                    ┌──────────────────────────┐
                    │ InstanceTelemetry        │
                    │ ├─ instance_id           │
                    │ ├─ hbm_utilization (%)   │
                    │ ├─ prefill_queue_depth   │
                    │ ├─ decode_queue_depth    │
                    │ ├─ num_cached_blocks     │
                    │ ├─ health_status         │
                    │ ├─ network_type          │
                    │ └─ timestamp             │
                    └──────────────────────────┘
                                     │
            ┌────────────────────────┼─────────────────┐
            │                        │                 │
            ▼                        ▼                 ▼
    ┌──────────────┐        ┌──────────────┐   ┌────────────┐
    │ State Machine│        │ Router       │   │ Frontend   │
    │ Reconciliate│        │ Scoring      │   │ SSE Stream │
    │ Block state │        │ (next req)   │   │ (metrics)  │
    └──────────────┘        └──────────────┘   └────────────┘


## Request Lifecycle in Simulation

```
Time 0.0ms:  ARRIVAL event for request_1
    ↓
    Router scores GPU0, GPU1 using LATEST telemetry
    → GPU0 has cache, GPU1 idle → GPU0 wins
    ↓
    Schedule PREFILL_COMPLETE @ time + prefill_time_ms
    Request moves to GPU0's prefill_queue
    ↓
Time 10.0ms: PREFILL_COMPLETE event for request_1
    ↓
    Block added to state_machine + GPU0 HBM
    Schedule DECODE_COMPLETE @ time + decode_time_ms
    Request moves to GPU0's decode_queue
    ↓
Time 100.0ms: HEARTBEAT event
    ↓
    Send updated telemetry to broker (GPU0 HBM up, GPU1 same)
    Next routing decision will see this telemetry
    ↓
Time 250.0ms: DECODE_COMPLETE event for request_1
    ↓
    Request complete, removed from active_requests
    GPU0 still has cached block
    ↓
Time 1500.0ms: ARRIVAL event for request_2 (different session)
    ↓
    Router scores with latest telemetry
    → GPU0 has shared system_prompt cache (higher score)
    → GPU1 is idle but no cache (lower score)
    → GPU0 still preferred due to cache_value - load_penalty
    ↓
    [Cycle repeats...]
```


## Phase 3 Extensions: Failures & P2P Transfers

```
┌─────────────────────────────────────────────────────────┐
│ GPU Instance Health Management                          │
│                                                         │
│ health_status: healthy | degraded | failed              │
│ failure_time: when failure injected                     │
│ recovery_deadline: when recovery window opens           │
│ network_type: rdma | tcp (for P2P transfers)            │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
    ┌──────────────────────┐
    │ Failure Injection    │
    │ (probabilistic)      │
    │                      │
    │ if random() < rate:  │
    │   GPU.inject_fail()  │
    │   Schedule RECOVERY  │
    └──────────┬───────────┘
               │
               ▼
    ┌──────────────────────────────┐
    │ Router sees failed GPU       │
    │ in telemetry, deprioritizes │
    │ or routes to healthy GPU     │
    └──────────────────────────────┘
               │
               ▼
    ┌──────────────────────────────┐
    │ PrefixStateMachine tracks    │
    │ P2P transfers in-flight      │
    │                              │
    │ initiate_transfer(           │
    │   from_gpu, to_gpu, block_id │
    │ )                            │
    │ → Scheduled as TRANSFER_     │
    │   COMPLETE event             │
    └──────────────────────────────┘
               │
               ▼
    ┌──────────────────────────────┐
    │ Transfer Latency             │
    │                              │
    │ RDMA:  block_size / 100Gbps  │
    │        (typically 10-15ms)   │
    │                              │
    │ TCP:   block_size / 10Gbps   │
    │        (typically 100-150ms) │
    │                              │
    │ If transfer fails → cascade  │
    │ to cache_miss (re-prefill)   │
    └──────────────────────────────┘
```


## Data Flow: Request → Routing → Execution

```
FRONTEND INPUT
    │
    ├─ num_sessions
    ├─ turns_per_session
    ├─ failure_rate
    ├─ network_type
    └─ stateful (bool)
         │
         ▼
    /simulate endpoint
    (create_simulation)
         │
         ▼
    EventDrivenSimulation.run()
         │
         ├─ Generate workload (MultiTurnWorkload)
         │
         ├─ Bootstrap all ARRIVAL events
         │
         ├─ Event loop:
         │  ├─ Pop earliest event
         │  ├─ Jump to event.time
         │  ├─ Dispatch on event.event_type
         │  │  ├─ ARRIVAL → _handle_request_arrival()
         │  │  │  └─ router.route() → RoutingDecision
         │  │  ├─ PREFILL_COMPLETE → _handle_prefill_complete()
         │  │  ├─ DECODE_COMPLETE → _handle_decode_complete()
         │  │  ├─ HEARTBEAT → _send_heartbeats()
         │  │  │  └─ Publish to telemetry_broker
         │  │  └─ TRANSFER_COMPLETE → _handle_transfer_complete()
         │  │
         │  └─ Emit SSE heartbeat event to frontend
         │     (progress, GPU metrics, request counters)
         │
         └─ Final metrics → complete event
              │
              ▼
         FRONTEND DISPLAY
         ├─ GPU Cards (HBM, cache hits, blocks)
         ├─ Key Metrics (throughput, latency)
         ├─ Comparison Charts
         └─ Expert Accordion (routing breakdown)
```


## Key Design Decisions

| Decision | Why | Tradeoff |
|----------|-----|----------|
| **Event-driven simulation** | Orders of magnitude faster than time-stepped | No continuous metrics between events |
| **Scoring over thresholds** | Prevents thundering herd via soft load penalties | Requires tuned weights, no closed-form optimum |
| **Separate prefill/decode tracking** | Prefill is 5x more expensive; should penalize differently | More state to track; slight overhead |
| **Single-owner blocks** | Simple state management; clear cache ownership | Can't easily represent "block on GPU0 AND GPU1" |
| **Telemetry broker (NATS-like)** | Decouples telemetry production from consumption | One-way pub/sub (no query/request semantics) |
| **Hardcoded weights** | Interpretable, reproducible routing decisions | Can't adapt to workload shifts (future: learning) |
| **P2P on-demand** | Transfers happen only when needed (failure recovery) | Transfer may fail mid-stream; fallback to prefill |
| **Noise-based tie-breaking** | Prevents all requests clustering on single GPU | Introduces randomness (slightly non-deterministic routes) |

