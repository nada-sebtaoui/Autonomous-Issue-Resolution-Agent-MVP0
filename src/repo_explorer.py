"""Finds the repo files most likely relevant to a given issue.

MVP approach: score files by keyword overlap between the issue text and
each file's path + contents. This is deliberately simple — Level 3 of the
roadmap swaps this module for embeddings/RAG over the repo without
touching the rest of the pipeline.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java",
    ".rb", ".php", ".rs", ".c", ".cpp", ".h",
}
IGNORE_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next"}
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "when", "from",
    "issue", "error", "should", "does", "have", "into", "about",
}


@dataclass
class ScoredFile:
    path: Path
    score: int
    snippet: str


class RepoExplorer:
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)

    def list_source_files(self) -> List[Path]:
        files = []
        for path in self.repo_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in IGNORE_DIRS for part in path.parts):
                continue
            if path.suffix in CODE_EXTENSIONS:
                files.append(path)
        return files

    def find_relevant_files(self, issue_title: str, issue_body: str, top_k: int = 8) -> List[ScoredFile]:
        keywords = self._extract_keywords(f"{issue_title}\n{issue_body}")
        scored = []
        for path in self.list_source_files():
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            score = self._score(path, text, keywords)
            if score > 0:
                scored.append(ScoredFile(path=path, score=score, snippet=self._best_snippet(text, keywords)))
        scored.sort(key=lambda f: f.score, reverse=True)
        return scored[:top_k]

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)
        keywords, seen = [], set()
        for w in words:
            w = w.lower()
            if w in STOPWORDS or w in seen:
                continue
            seen.add(w)
            keywords.append(w)
        return keywords[:25]

    @staticmethod
    def _score(path: Path, text: str, keywords: List[str]) -> int:
        score = 0
        lower_text = text.lower()
        lower_path = str(path).lower()
        for kw in keywords:
            score += 3 * lower_path.count(kw)  # path matches weighted higher
            score += lower_text.count(kw)
        return score

    @staticmethod
    def _best_snippet(text: str, keywords: List[str], context_lines: int = 6) -> str:
        lines = text.splitlines()
        if not lines:
            return ""
        best_idx, best_hits = 0, -1
        for i, line in enumerate(lines):
            hits = sum(1 for kw in keywords if kw in line.lower())
            if hits > best_hits:
                best_hits, best_idx = hits, i
        start, end = max(0, best_idx - context_lines), min(len(lines), best_idx + context_lines)
        return "\n".join(lines[start:end])
