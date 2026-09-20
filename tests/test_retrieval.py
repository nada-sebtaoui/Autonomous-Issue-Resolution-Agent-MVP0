import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.retrieval import CodeRetriever


def test_hybrid_retrieval_ranks_relevant_chunk_first(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def login(email, password):\n"
        "    if email is None:\n"
        "        return {'error': 'email required'}\n"
        "    return {'ok': True}\n"
    )
    (tmp_path / "billing.py").write_text(
        "def charge_invoice(invoice_id):\n"
        "    return {'paid': True}\n"
    )

    results = CodeRetriever(tmp_path).retrieve(
        "Login returns 500 when email is missing",
        "POST /login crashes when email is absent.",
        top_k=3,
        mode="hybrid",
    )

    assert results
    assert results[0].relative_path == "auth.py"
    assert results[0].symbol == "login"
    assert "email" in results[0].snippet
    assert results[0].hybrid_score > 0
    assert "matches" in results[0].reason


def test_retrieval_returns_empty_for_empty_repository(tmp_path):
    assert CodeRetriever(tmp_path).retrieve("anything", "nothing here") == []


def test_retrieval_ignores_vendored_directories(tmp_path):
    vendor_dir = tmp_path / "node_modules"
    vendor_dir.mkdir()
    (vendor_dir / "auth.py").write_text("def login(email): return email\n")

    results = CodeRetriever(tmp_path).retrieve("login email", "", top_k=5)

    assert results == []


def test_retrieval_modes_are_available(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def authenticate_user(token):\n"
        "    return token == 'valid'\n"
    )

    keyword_results = CodeRetriever(tmp_path).retrieve(
        "authentication token is rejected",
        "token validation fails",
        mode="keyword",
    )
    semantic_results = CodeRetriever(tmp_path).retrieve(
        "authentication token is rejected",
        "token validation fails",
        mode="semantic",
    )
    hybrid_results = CodeRetriever(tmp_path).retrieve(
        "authentication token is rejected",
        "token validation fails",
        mode="hybrid",
    )

    assert keyword_results
    assert semantic_results
    assert hybrid_results
    assert keyword_results[0].lexical_score >= 0
    assert semantic_results[0].semantic_score >= 0
    assert hybrid_results[0].hybrid_score >= 0
