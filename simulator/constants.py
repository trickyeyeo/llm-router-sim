"""
Realistic constants for GPU backends and models.

These values are based on published benchmarks and real-world deployments.
All measurements in practical units (tokens/sec, GB, MB/token, ms, etc.)
"""

from dataclasses import dataclass


@dataclass
class NetworkConfig:
    """Configuration for network capabilities (for P2P KV transfers)."""

    network_type: str  # "rdma" or "tcp"
    bandwidth_gbps: float  # Gigabits per second
    bandwidth_bytes_per_ms: float  # Bytes per millisecond (for simulation)


# Network technology options
NETWORK_RDMA = NetworkConfig(
    network_type="rdma",
    bandwidth_gbps=100.0,
    bandwidth_bytes_per_ms=12_500.0,  # 100 Gbps / 8 bits per byte / 1000 ms
)

NETWORK_TCP = NetworkConfig(
    network_type="tcp",
    bandwidth_gbps=10.0,
    bandwidth_bytes_per_ms=1_250.0,  # 10 Gbps / 8 bits per byte / 1000 ms
)


@dataclass
class FailureInjectionConfig:
    """Configuration for failure injection in simulation (Phase 3)."""

    enabled: bool = False
    failure_rate: float = 0.0  # Probability of failure per request (0.0-1.0)
    failure_detection_delay_ms: float = 100.0  # Heartbeat interval for detection
    failure_recovery_time_ms: float = 5000.0  # Time to recover from failure
    failure_type: str = "random"  # "random" | "cascading" | "periodic" (Phase 3)


@dataclass
class RoutingWeights:
    """Weights for scoring-based router (prevents thundering herds)."""

    # Cache value weight: (matched_tokens / total_tokens) * prefill_time_saved * w_cache
    w_cache: float = 1.0

    # Queue depth penalties (higher weight = stronger penalty for queue)
    w_prefill_queue: float = 0.1  # Per prefill request in queue (heavy: long latency)
    w_decode_queue: float = 0.05  # Per decode request in queue (lighter: fast latency)

    # HBM utilization penalty (soft threshold, not binary)
    w_hbm: float = 2.0  # Penalty scales with utilization

    # Tie-breaking noise: add random value when scores are close
    noise_epsilon: float = 1.0  # Scores within this range get noise
    noise_magnitude: float = 0.5  # Max random noise to add


# Default weights (tuned to prevent thundering herds while respecting cache)
# Key insight: w_prefill_queue is high because each queued prefill adds ~5-10s latency
# w_cache should be comparable so 256ms cache advantage doesn't override 10 queued requests
DEFAULT_ROUTING_WEIGHTS = RoutingWeights(
    w_cache=1.0,
    w_prefill_queue=0.5,  # Each queued prefill costs ~0.5 points (high latency impact)
    w_decode_queue=0.1,   # Decode queues are lighter (decode is fast)
    w_hbm=3.0,            # HBM utilization penalty (indirect impact on future hits)
    noise_epsilon=1.0,
    noise_magnitude=0.5,
)


@dataclass
class ModelConfig:
    """Configuration for an LLM or SLM model."""

    model_id: str
    hidden_dim: int
    num_layers: int
    kv_cache_bytes_per_token: int  # Approximate KV cache size per token (compressed)
    model_size_gb: float  # Model weights size


# LLMs (on H100)
LLAMA_405B = ModelConfig(
    model_id="Llama-405B",
    hidden_dim=14336,
    num_layers=126,
    kv_cache_bytes_per_token=1_500_000,  # ~1.5MB per token (post-compression)
    model_size_gb=810.0,  # ~810 GB for weights
)

LLAMA_70B = ModelConfig(
    model_id="Llama-70B",
    hidden_dim=8192,
    num_layers=80,
    kv_cache_bytes_per_token=512_000,  # ~512KB per token
    model_size_gb=140.0,  # ~140 GB
)

# SLMs (on L4)
LLAMA_8B = ModelConfig(
    model_id="Llama-8B",
    hidden_dim=4096,
    num_layers=32,
    kv_cache_bytes_per_token=256_000,  # ~256KB per token
    model_size_gb=16.0,  # ~16 GB
)

LLAMA_1B = ModelConfig(
    model_id="Llama-1B",
    hidden_dim=2048,
    num_layers=16,
    kv_cache_bytes_per_token=64_000,  # ~64KB per token
    model_size_gb=2.0,  # ~2 GB
)


@dataclass
class GPUConfig:
    """Configuration for a GPU instance."""

    gpu_name: str
    hbm_capacity_gb: int
    # Throughput: tokens processed per second (entire batch, prefill phase)
    prefill_throughput_tokens_per_sec: int
    # For decode: tokens per request per second (single token gen per request)
    # We model as: each request in batch takes this latency per token
    decode_latency_per_token_ms: float
    # Maximum batch size during decode
    max_batch_size: int
    # Network capability for P2P KV transfers
    network_type: str = "rdma"  # "rdma" or "tcp"


# H100 80GB (for LLMs like 405B, 70B)
H100_80GB = GPUConfig(
    gpu_name="H100-80GB",
    hbm_capacity_gb=80,
    # Prefill: memory-bandwidth bound, ~1500-2000 tokens/sec for typical models
    # (Depends on model size; using conservative estimate for 70B+)
    prefill_throughput_tokens_per_sec=1500,
    # Decode: ~1-2ms per token at batch size 1, scales sublinearly with batch
    # Using 1ms as baseline (1000 tokens/sec aggregate)
    decode_latency_per_token_ms=1.0,
    max_batch_size=256,
)

# L4 24GB (for SLMs like 8B, 1B)
L4_24GB = GPUConfig(
    gpu_name="L4-24GB",
    hbm_capacity_gb=24,
    # Prefill: ~600-900 tokens/sec for small models like 8B
    prefill_throughput_tokens_per_sec=800,
    # Decode: ~2-3ms per token at batch size 1
    decode_latency_per_token_ms=2.0,
    max_batch_size=128,
)


# Realistic deployments
DEPLOYMENT_LLAMA_LLM = {
    "gpu_config": H100_80GB,
    "model_config": LLAMA_405B,
}

DEPLOYMENT_LLAMA_SLM = {
    "gpu_config": L4_24GB,
    "model_config": LLAMA_8B,
}

DEPLOYMENT_MIXED = [
    {"gpu_config": H100_80GB, "model_config": LLAMA_70B},  # H100 with 70B
    {"gpu_config": L4_24GB, "model_config": LLAMA_8B},  # L4 with 8B
]


def create_gpu_instance_config(
    instance_id: str, gpu_config: GPUConfig, model_config: ModelConfig
) -> "GPUInstanceConfig":
    """Helper to create GPUInstanceConfig from GPU and model configs."""
    from simulator.gpu_backend import GPUInstanceConfig

    return GPUInstanceConfig(
        instance_id=instance_id,
        model_id=model_config.model_id,
        hbm_capacity_bytes=gpu_config.hbm_capacity_gb * 1024 * 1024 * 1024,
        prefill_throughput_tokens_per_sec=gpu_config.prefill_throughput_tokens_per_sec,
        decode_latency_per_token_ms=gpu_config.decode_latency_per_token_ms,
        max_batch_size=gpu_config.max_batch_size,
    )
