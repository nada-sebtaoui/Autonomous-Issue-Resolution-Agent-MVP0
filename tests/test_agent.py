import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.config import Config
from src.repo_explorer import RepoExplorer


def test_find_relevant_files_ranks_the_right_file_first(tmp_path):
    (tmp_path / "auth_controller.py").write_text(
        "def login(email, password):\n"
        "    if email is None:\n"
        "        return 500\n"
        "    return 200\n"
    )
    (tmp_path / "unrelated.py").write_text("def add(a, b):\n    return a + b\n")

    explorer = RepoExplorer(tmp_path)
    results = explorer.find_relevant_files(
        issue_title="Login returns 500 when email is missing",
        issue_body="POST /login with no email field crashes with a 500 error.",
        top_k=5,
    )

    assert results, "expected at least one relevant file"
    assert results[0].path.name == "auth_controller.py"


def test_find_relevant_files_ignores_vendored_dirs(tmp_path):
    vendor_dir = tmp_path / "node_modules"
    vendor_dir.mkdir()
    (vendor_dir / "login.py").write_text("def login(email): return 500\n")

    explorer = RepoExplorer(tmp_path)
    files = explorer.list_source_files()

    assert files == []


def test_config_requires_api_key(monkeypatch):
    monkeypatch.setenv("AI_ISSUE_AGENT_SKIP_DOTENV", "1")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(EnvironmentError):
        Config.from_env()


def test_config_reads_from_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test-123")
    monkeypatch.setenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("GROQ_MODEL_A", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_MODEL_B", "groq/compound")
    monkeypatch.setenv("GROQ_SKIP_TEMPERATURE", "groq/compound")
    monkeypatch.setenv("RETRIEVAL_TOP_K", "5")
    monkeypatch.setenv("RETRIEVAL_MODE", "keyword")
    monkeypatch.setenv("RETRIEVAL_LEXICAL_WEIGHT", "0.8")
    monkeypatch.setenv("RETRIEVAL_SEMANTIC_WEIGHT", "0.2")
    monkeypatch.setenv("DOCKER_IMAGE", "python:3.11-slim")
    monkeypatch.setenv("DOCKER_TIMEOUT", "90")
    monkeypatch.setenv("DOCKER_TEST_COMMAND", "python -m pytest tests")
    monkeypatch.setenv("DOCKER_MEMORY", "256m")
    monkeypatch.setenv("DOCKER_CPUS", "0.5")
    monkeypatch.setenv("DOCKER_NETWORK_DISABLED", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-test-456")
    config = Config.from_env()
    assert config.groq_api_key == "gsk_test-123"
    assert config.groq_base_url == "https://api.groq.com/openai/v1"
    assert config.groq_model_a == "openai/gpt-oss-120b"
    assert config.groq_model_b == "groq/compound"
    assert "groq/compound" in config.groq_skip_temperature
    assert config.retrieval_top_k == 5
    assert config.retrieval_mode == "keyword"
    assert config.retrieval_lexical_weight == 0.8
    assert config.retrieval_semantic_weight == 0.2
    assert config.docker_image == "python:3.11-slim"
    assert config.docker_timeout == 90
    assert config.docker_test_command == "python -m pytest tests"
    assert config.docker_memory == "256m"
    assert config.docker_cpus == "0.5"
    assert config.docker_network_disabled is True
    assert config.github_token == "ghp-test-456"


def test_planner_skips_temperature_for_listed_models():
    from src.llm_planner import LLMPlanner

    planner = LLMPlanner(
        api_key="gsk_test",
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        fallback_model="groq/compound",
        skip_temperature=frozenset({"groq/compound"}),
    )
    messages = [{"role": "user", "content": "hi"}]

    with_temp = planner._chat_kwargs("openai/gpt-oss-120b", messages)
    assert with_temp["temperature"] == 0

    without_temp = planner._chat_kwargs("groq/compound", messages)
    assert "temperature" not in without_temp
