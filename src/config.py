"""Runtime configuration for the agent, loaded from environment variables."""

import os
from dataclasses import dataclass
from typing import FrozenSet


def _csv_set(value: str) -> FrozenSet[str]:
    return frozenset(part.strip() for part in value.split(",") if part.strip())


@dataclass
class Config:
    github_token: str
    groq_api_key: str
    groq_base_url: str
    groq_model_a: str
    groq_model_b: str
    groq_skip_temperature: FrozenSet[str]
    max_files_to_inspect: int = 8
    max_debug_iterations: int = 3
    retrieval_top_k: int = 8
    retrieval_mode: str = "hybrid"
    retrieval_lexical_weight: float = 0.65
    retrieval_semantic_weight: float = 0.35
    docker_image: str = "python:3.11-slim"
    docker_timeout: int = 120
    docker_test_command: str = "python -m pytest -q"
    docker_memory: str = ""
    docker_cpus: str = ""
    docker_network_disabled: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        # Load .env if python-dotenv is available; otherwise fall back to
        # whatever is already in the environment.
        if os.environ.get("AI_ISSUE_AGENT_SKIP_DOTENV") != "1":
            try:
                from dotenv import load_dotenv

                load_dotenv()
            except ImportError:
                pass

        github_token = os.environ.get("GITHUB_TOKEN", "")
        groq_api_key = os.environ.get("GROQ_API_KEY", "")
        groq_base_url = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        groq_model_a = os.environ.get("GROQ_MODEL_A", "openai/gpt-oss-120b")
        groq_model_b = os.environ.get("GROQ_MODEL_B", "groq/compound")
        groq_skip_temperature = _csv_set(
            os.environ.get("GROQ_SKIP_TEMPERATURE", "groq/compound")
        )
        retrieval_top_k = int(os.environ.get("RETRIEVAL_TOP_K", "8"))
        retrieval_mode = os.environ.get("RETRIEVAL_MODE", "hybrid")
        retrieval_lexical_weight = float(os.environ.get("RETRIEVAL_LEXICAL_WEIGHT", "0.65"))
        retrieval_semantic_weight = float(os.environ.get("RETRIEVAL_SEMANTIC_WEIGHT", "0.35"))
        docker_image = os.environ.get("DOCKER_IMAGE", "python:3.11-slim")
        docker_timeout = int(os.environ.get("DOCKER_TIMEOUT", "120"))
        docker_test_command = os.environ.get("DOCKER_TEST_COMMAND", "python -m pytest -q")
        docker_memory = os.environ.get("DOCKER_MEMORY", "")
        docker_cpus = os.environ.get("DOCKER_CPUS", "")
        docker_network_disabled = os.environ.get("DOCKER_NETWORK_DISABLED", "false").lower() == "true"

        if not groq_api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. Copy .env.example to .env "
                "and fill in your key, or export it in your shell."
            )

        return cls(
            github_token=github_token,
            groq_api_key=groq_api_key,
            groq_base_url=groq_base_url,
            groq_model_a=groq_model_a,
            groq_model_b=groq_model_b,
            groq_skip_temperature=groq_skip_temperature,
            retrieval_top_k=retrieval_top_k,
            retrieval_mode=retrieval_mode,
            retrieval_lexical_weight=retrieval_lexical_weight,
            retrieval_semantic_weight=retrieval_semantic_weight,
            docker_image=docker_image,
            docker_timeout=docker_timeout,
            docker_test_command=docker_test_command,
            docker_memory=docker_memory,
            docker_cpus=docker_cpus,
            docker_network_disabled=docker_network_disabled,
        )
