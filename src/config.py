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

    @classmethod
    def from_env(cls) -> "Config":
        # Load .env if python-dotenv is available; otherwise fall back to
        # whatever is already in the environment.
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
        )
