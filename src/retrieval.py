"""Modular code retrieval for GitHub issue context.

This module keeps the MVP keyword approach available while adding a richer
chunk-level retrieval API. The semantic scorer is intentionally lightweight and
local for now: it uses token-vector cosine similarity so the project remains
runnable without a heavy vector database. The interface is designed so a real
embedding + FAISS backend can replace it later without changing the agent.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from .repo_explorer import CODE_EXTENSIONS, IGNORE_DIRS, STOPWORDS


SYMBOL_PATTERN = re.compile(
    r"^\s*(?:async\s+def|def|class|function|func)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)


@dataclass
class CodeChunk:
    path: Path
    relative_path: str
    language: str
    symbol: str
    start_line: int
    end_line: int
    content: str
    chunk_id: str


@dataclass
class RetrievalResult:
    path: Path
    relative_path: str
    symbol: str
    start_line: int
    end_line: int
    lexical_score: float
    semantic_score: float
    hybrid_score: float
    reason: str
    snippet: str

    @property
    def score(self) -> float:
        return self.hybrid_score


class CodeRetriever:
    """Retrieves relevant code chunks using lexical, symbol, and semantic signals."""

    def __init__(
        self,
        repo_root: Path,
        lexical_weight: float = 0.65,
        semantic_weight: float = 0.35,
        chunk_size: int = 80,
        chunk_overlap: int = 15,
    ):
        self.repo_root = Path(repo_root)
        self.lexical_weight = lexical_weight
        self.semantic_weight = semantic_weight
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def retrieve(
        self,
        issue_title: str,
        issue_body: str,
        top_k: int = 8,
        mode: str = "hybrid",
    ) -> List[RetrievalResult]:
        query = f"{issue_title}\n{issue_body}"
        keywords = self._extract_keywords(query)
        query_vector = self._token_vector(query)
        results: List[RetrievalResult] = []

        for chunk in self._iter_chunks():
            lexical_score = self._lexical_score(chunk, keywords)
            semantic_score = self._semantic_score(query_vector, chunk.content)
            hybrid_score = self._combine_scores(lexical_score, semantic_score, mode)
            if hybrid_score <= 0:
                continue
            results.append(
                RetrievalResult(
                    path=chunk.path,
                    relative_path=chunk.relative_path,
                    symbol=chunk.symbol,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    lexical_score=lexical_score,
                    semantic_score=semantic_score,
                    hybrid_score=hybrid_score,
                    reason=self._reason(chunk, keywords, lexical_score, semantic_score),
                    snippet=chunk.content,
                )
            )

        results.sort(key=lambda item: item.hybrid_score, reverse=True)
        return results[:top_k]

    def _combine_scores(self, lexical_score: float, semantic_score: float, mode: str) -> float:
        if mode == "keyword":
            return lexical_score
        if mode == "semantic":
            return semantic_score
        return (self.lexical_weight * lexical_score) + (self.semantic_weight * semantic_score)

    def _iter_chunks(self) -> Iterable[CodeChunk]:
        for path in self._list_source_files():
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            yield from self._chunk_file(path, text)

    def _list_source_files(self) -> List[Path]:
        files = []
        for path in self.repo_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in IGNORE_DIRS for part in path.parts):
                continue
            if path.suffix in CODE_EXTENSIONS:
                files.append(path)
        return files

    def _chunk_file(self, path: Path, text: str) -> Iterable[CodeChunk]:
        lines = text.splitlines()
        if not lines:
            return

        relative_path = path.relative_to(self.repo_root).as_posix()
        language = path.suffix.lstrip(".")
        symbol_lines = self._symbol_lines(lines)

        if symbol_lines:
            for index, (line_no, symbol) in enumerate(symbol_lines):
                next_line = symbol_lines[index + 1][0] if index + 1 < len(symbol_lines) else len(lines) + 1
                start = max(1, line_no)
                end = min(len(lines), next_line - 1)
                content = "\n".join(lines[start - 1 : end])
                yield CodeChunk(
                    path=path,
                    relative_path=relative_path,
                    language=language,
                    symbol=symbol,
                    start_line=start,
                    end_line=end,
                    content=content,
                    chunk_id=f"{relative_path}:{start}-{end}",
                )
            return

        step = max(1, self.chunk_size - self.chunk_overlap)
        for start_idx in range(0, len(lines), step):
            end_idx = min(len(lines), start_idx + self.chunk_size)
            content = "\n".join(lines[start_idx:end_idx])
            yield CodeChunk(
                path=path,
                relative_path=relative_path,
                language=language,
                symbol="",
                start_line=start_idx + 1,
                end_line=end_idx,
                content=content,
                chunk_id=f"{relative_path}:{start_idx + 1}-{end_idx}",
            )
            if end_idx == len(lines):
                break

    @staticmethod
    def _symbol_lines(lines: Sequence[str]) -> List[tuple[int, str]]:
        symbols = []
        for index, line in enumerate(lines, start=1):
            match = SYMBOL_PATTERN.match(line)
            if match:
                symbols.append((index, match.group(1)))
        return symbols

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)
        keywords, seen = [], set()
        for word in words:
            normalized = word.lower()
            if normalized in STOPWORDS or normalized in seen:
                continue
            seen.add(normalized)
            keywords.append(normalized)
        return keywords[:30]

    @staticmethod
    def _token_vector(text: str) -> Counter[str]:
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
        return Counter(token for token in tokens if token not in STOPWORDS)

    def _lexical_score(self, chunk: CodeChunk, keywords: Sequence[str]) -> float:
        if not keywords:
            return 0.0

        content = chunk.content.lower()
        path = chunk.relative_path.lower()
        symbol = chunk.symbol.lower()
        raw_score = 0.0
        for keyword in keywords:
            raw_score += 3.0 * path.count(keyword)
            raw_score += 2.0 * symbol.count(keyword)
            raw_score += content.count(keyword)

        return min(1.0, raw_score / max(8.0, len(keywords)))

    def _semantic_score(self, query_vector: Counter[str], content: str) -> float:
        chunk_vector = self._token_vector(content)
        return self._cosine_similarity(query_vector, chunk_vector)

    @staticmethod
    def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
        if not left or not right:
            return 0.0

        common = set(left) & set(right)
        numerator = sum(left[token] * right[token] for token in common)
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)

    @staticmethod
    def _reason(
        chunk: CodeChunk,
        keywords: Sequence[str],
        lexical_score: float,
        semantic_score: float,
    ) -> str:
        path = chunk.relative_path.lower()
        content = chunk.content.lower()
        symbol = chunk.symbol.lower()
        matches = []
        for keyword in keywords:
            if keyword in path:
                matches.append(f'path matches "{keyword}"')
            elif symbol and keyword in symbol:
                matches.append(f'symbol matches "{keyword}"')
            elif keyword in content:
                matches.append(f'content matches "{keyword}"')
            if len(matches) == 3:
                break

        score_note = f"lexical={lexical_score:.2f}, semantic={semantic_score:.2f}"
        if matches:
            return "; ".join(matches + [score_note])
        return score_note
