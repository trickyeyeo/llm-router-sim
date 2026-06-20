"""
Debug test: verify workload generator produces arrivals.
"""

from simulator.workload import RAGWorkload
from simulator.constants import LLAMA_70B

# Small workload: 10 req/sec
workload = RAGWorkload(
    arrival_rate_requests_per_sec=10.0,
    system_prompt_tokens=512,
    retrieval_context_tokens=2048,
    user_query_tokens=128,
    retrieval_reuse_probability=0.4,
    output_tokens_mean=256,
    kv_cache_bytes_per_token=LLAMA_70B.kv_cache_bytes_per_token,
    seed=42,
)

# Generate arrivals up to 100ms
print("Generating arrivals up to 100ms...")
arrivals = workload.generate_arrivals(100.0)

print(f"Generated {len(arrivals)} requests")
for i, req in enumerate(arrivals[:5]):
    print(f"  Request {i}: arrival_time={req.arrival_time:.2f}ms, output_tokens={req.target_output_tokens}")

if len(arrivals) > 5:
    print(f"  ... and {len(arrivals) - 5} more")
