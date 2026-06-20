"""
Workload generator: creates requests with realistic prefix patterns.

Supports common CUJs:
- RAG: shared retrieval context across queries
- Few-shot: shared examples across batch
- Multi-turn: shared conversation history
- Mixed models: different request types
"""

from dataclasses import dataclass
from typing import List, Callable, Optional
import random


@dataclass
class PrefixBlock:
    """Represents one block in a request's prefix chain."""

    name: str  # 'system', 'retrieval', 'user_turn', etc.
    hash_value: str  # Hash identifying this block
    num_tokens: int
    kv_cache_bytes: int


@dataclass
class Request:
    """A single request."""

    request_id: str
    arrival_time: float  # ms
    prefix_blocks: List[PrefixBlock]  # App-defined prefix structure
    target_output_tokens: int  # Tokens to generate
    model_id: str  # Target model ('H100-405B', 'L4-8B')

    @property
    def prefix_hashes(self) -> List[str]:
        """Hashes in order for prefix chain query."""
        return [block.hash_value for block in self.prefix_blocks]

    @property
    def total_prefix_tokens(self) -> int:
        return sum(b.num_tokens for b in self.prefix_blocks)

    @property
    def total_kv_cache_bytes(self) -> int:
        return sum(b.kv_cache_bytes for b in self.prefix_blocks)


class WorkloadGenerator:
    """Base class for workload generators."""

    def __init__(self, seed: int = 42):
        random.seed(seed)

    def generate_arrivals(self, current_time: float) -> List[Request]:
        """Generate requests arriving at current_time."""
        raise NotImplementedError


class PoissonWorkload(WorkloadGenerator):
    """
    Poisson arrival process with fixed request rate.

    Requests have a simple, configurable prefix structure.
    """

    def __init__(
        self,
        arrival_rate_requests_per_sec: float,
        prefix_factory: Callable[[], List[PrefixBlock]],
        output_tokens_factory: Callable[[], int],
        model_factory: Callable[[], str],
        seed: int = 42,
    ):
        super().__init__(seed)
        self.arrival_rate = arrival_rate_requests_per_sec
        self.prefix_factory = prefix_factory
        self.output_tokens_factory = output_tokens_factory
        self.model_factory = model_factory
        self.request_counter = 0
        self.last_arrival_time = -1e9  # Start far in the past to allow first arrivals

    def generate_arrivals(self, current_time: float) -> List[Request]:
        """Generate Poisson-distributed arrivals."""
        requests = []

        # Inter-arrival time is exponentially distributed
        while True:
            inter_arrival_ms = random.expovariate(
                self.arrival_rate / 1000.0
            )  # Convert to per ms
            next_arrival = self.last_arrival_time + inter_arrival_ms

            if next_arrival > current_time:
                self.last_arrival_time = next_arrival
                break

            self.request_counter += 1
            requests.append(
                Request(
                    request_id=f"req_{self.request_counter}",
                    arrival_time=next_arrival,
                    prefix_blocks=self.prefix_factory(),
                    target_output_tokens=self.output_tokens_factory(),
                    model_id=self.model_factory(),
                )
            )
            self.last_arrival_time = next_arrival

        return requests


class RAGWorkload(WorkloadGenerator):
    """
    RAG workload: requests share common retrieval context.

    Prefix structure:
    - Block 1: System prompt (constant across all requests)
    - Block 2: Retrieval context (shared by ~N% of requests)
    - Block 3: User query (always different)
    """

    def __init__(
        self,
        arrival_rate_requests_per_sec: float,
        system_prompt_tokens: int = 512,
        retrieval_context_tokens: int = 2048,
        user_query_tokens: int = 128,
        retrieval_reuse_probability: float = 0.4,
        output_tokens_mean: int = 256,
        seed: int = 42,
    ):
        super().__init__(seed)
        self.arrival_rate = arrival_rate_requests_per_sec
        self.system_prompt_tokens = system_prompt_tokens
        self.retrieval_context_tokens = retrieval_context_tokens
        self.user_query_tokens = user_query_tokens
        self.retrieval_reuse_probability = retrieval_reuse_probability
        self.output_tokens_mean = output_tokens_mean
        self.request_counter = 0
        self.last_arrival_time = -1e9  # Start far in the past

        # KV cache size heuristic: ~256 bytes per token (depends on model)
        self.kv_bytes_per_token = 256

        # Retrieval contexts pool (to model reuse)
        self.retrieval_contexts = {}
        self.next_retrieval_id = 0
        self.active_retrieval_id = 0

    def _get_system_prompt_block(self) -> PrefixBlock:
        return PrefixBlock(
            name="system",
            hash_value="hash_system_prompt",
            num_tokens=self.system_prompt_tokens,
            kv_cache_bytes=self.system_prompt_tokens * self.kv_bytes_per_token,
        )

    def _get_retrieval_block(self) -> PrefixBlock:
        """Get retrieval context (reused or new)."""
        if random.random() < self.retrieval_reuse_probability:
            # Reuse active retrieval context
            ret_id = self.active_retrieval_id
        else:
            # New retrieval context
            self.next_retrieval_id += 1
            ret_id = self.next_retrieval_id
            self.active_retrieval_id = ret_id

        hash_val = f"hash_retrieval_{ret_id}"
        return PrefixBlock(
            name="retrieval",
            hash_value=hash_val,
            num_tokens=self.retrieval_context_tokens,
            kv_cache_bytes=self.retrieval_context_tokens * self.kv_bytes_per_token,
        )

    def _get_user_query_block(self) -> PrefixBlock:
        return PrefixBlock(
            name="user_query",
            hash_value=f"hash_query_{self.request_counter}",
            num_tokens=self.user_query_tokens,
            kv_cache_bytes=self.user_query_tokens * self.kv_bytes_per_token,
        )

    def generate_arrivals(self, current_time: float) -> List[Request]:
        """Generate RAG requests with shared retrieval context."""
        requests = []

        while True:
            inter_arrival_ms = random.expovariate(
                self.arrival_rate / 1000.0
            )
            next_arrival = self.last_arrival_time + inter_arrival_ms

            if next_arrival > current_time:
                self.last_arrival_time = next_arrival
                break

            self.request_counter += 1
            output_tokens = max(1, int(random.gauss(self.output_tokens_mean, 50)))

            requests.append(
                Request(
                    request_id=f"req_{self.request_counter}",
                    arrival_time=next_arrival,
                    prefix_blocks=[
                        self._get_system_prompt_block(),
                        self._get_retrieval_block(),
                        self._get_user_query_block(),
                    ],
                    target_output_tokens=output_tokens,
                    model_id="H100-405B",
                )
            )
            self.last_arrival_time = next_arrival

        return requests


class FewShotWorkload(WorkloadGenerator):
    """
    Few-shot workload: requests share common examples.

    Prefix structure:
    - Block 1: System prompt
    - Block 2: Few-shot examples (shared by all requests in batch)
    - Block 3: User query (varies per request)
    """

    def __init__(
        self,
        arrival_rate_requests_per_sec: float,
        system_prompt_tokens: int = 256,
        examples_tokens: int = 1024,
        user_query_tokens: int = 128,
        output_tokens_mean: int = 256,
        batch_size: int = 32,
        seed: int = 42,
    ):
        super().__init__(seed)
        self.arrival_rate = arrival_rate_requests_per_sec
        self.system_prompt_tokens = system_prompt_tokens
        self.examples_tokens = examples_tokens
        self.user_query_tokens = user_query_tokens
        self.output_tokens_mean = output_tokens_mean
        self.batch_size = batch_size
        self.request_counter = 0
        self.last_arrival_time = -1e9  # Start far in the past
        self.batch_counter = 0

        self.kv_bytes_per_token = 256

    def generate_arrivals(self, current_time: float) -> List[Request]:
        """Generate batched few-shot requests."""
        requests = []

        while True:
            inter_arrival_ms = random.expovariate(
                self.arrival_rate / 1000.0
            )
            next_arrival = self.last_arrival_time + inter_arrival_ms

            if next_arrival > current_time:
                self.last_arrival_time = next_arrival
                break

            self.request_counter += 1

            # Batch ID: requests in same batch share examples
            batch_id = self.request_counter // self.batch_size
            if batch_id != self.batch_counter:
                self.batch_counter = batch_id

            output_tokens = max(1, int(random.gauss(self.output_tokens_mean, 50)))

            requests.append(
                Request(
                    request_id=f"req_{self.request_counter}",
                    arrival_time=next_arrival,
                    prefix_blocks=[
                        PrefixBlock(
                            name="system",
                            hash_value="hash_system",
                            num_tokens=self.system_prompt_tokens,
                            kv_cache_bytes=self.system_prompt_tokens
                            * self.kv_bytes_per_token,
                        ),
                        PrefixBlock(
                            name="examples",
                            hash_value=f"hash_examples_batch_{batch_id}",
                            num_tokens=self.examples_tokens,
                            kv_cache_bytes=self.examples_tokens
                            * self.kv_bytes_per_token,
                        ),
                        PrefixBlock(
                            name="query",
                            hash_value=f"hash_query_{self.request_counter}",
                            num_tokens=self.user_query_tokens,
                            kv_cache_bytes=self.user_query_tokens
                            * self.kv_bytes_per_token,
                        ),
                    ],
                    target_output_tokens=output_tokens,
                    model_id="H100-405B",
                )
            )
            self.last_arrival_time = next_arrival

        return requests
