"""Safe unified-diff validation and application."""

import subprocess
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Set


class PatchValidationError(ValueError):
    """Raised when an LLM-generated patch is unsafe or invalid."""


@dataclass
class PatchApplicationResult:
    applied: bool
    diff: str
    error: str = ""


def normalize_unified_diff(patch: str) -> str:
    """Normalize common LLM diff formatting issues without changing intent."""

    patch = patch if patch.endswith("\n") else f"{patch}\n"
    lines = patch.splitlines(keepends=True)
    normalized = []
    index = 0

    while index < len(lines):
        line = lines[index]
        match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", line)
        if not match:
            normalized.append(line)
            index += 1
            continue

        old_start = match.group(1)
        new_start = match.group(2)
        suffix = match.group(3).rstrip("\n")
        hunk_lines = []
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if candidate.startswith(("diff --git ", "--- ", "+++ ", "@@ ")):
                break
            hunk_lines.append(candidate)
            index += 1

        old_count = sum(1 for item in hunk_lines if item.startswith((" ", "-")))
        new_count = sum(1 for item in hunk_lines if item.startswith((" ", "+")))
        normalized.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{suffix}\n")
        normalized.extend(hunk_lines)

    return "".join(normalized)


class PatchManager:
    """Validates and applies a single-file unified diff inside a repository."""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()

    def validate_target_file(self, target_file: str) -> Path:
        if not target_file:
            raise PatchValidationError("target_file is required")

        target = Path(target_file)
        if target.is_absolute() or ".." in target.parts:
            raise PatchValidationError("target_file must be a relative path inside the repository")

        resolved = (self.repo_root / target).resolve()
        if not resolved.is_relative_to(self.repo_root):
            raise PatchValidationError("target_file escapes the repository")
        if not resolved.exists():
            raise PatchValidationError(f"target_file does not exist: {target_file}")
        if not resolved.is_file():
            raise PatchValidationError(f"target_file is not a file: {target_file}")

        return resolved

    def validate_patch(self, target_file: str, patch: str) -> None:
        self.validate_target_file(target_file)
        if not patch or not patch.strip():
            raise PatchValidationError("patch is required")

        patch = self._normalize_patch_text(patch)
        expected = self._normalize_path(target_file)
        paths = self._extract_patch_paths(patch)
        if not paths:
            raise PatchValidationError("patch does not contain a target file")
        if paths != {expected}:
            raise PatchValidationError(
                f"patch targets {sorted(paths)}, expected only {expected}"
            )

        check = self._run_git_apply(patch, check=True)
        if check.returncode != 0:
            error = check.stderr.strip() or check.stdout.strip()
            raise PatchValidationError(f"patch cannot be applied: {error}")

    def apply_patch(self, target_file: str, patch: str) -> PatchApplicationResult:
        patch = self._normalize_patch_text(patch)
        try:
            self.validate_patch(target_file, patch)
            result = self._run_git_apply(patch, check=False)
            if result.returncode != 0:
                error = result.stderr.strip() or result.stdout.strip()
                return PatchApplicationResult(applied=False, diff=patch, error=error)
            return PatchApplicationResult(applied=True, diff=patch)
        except PatchValidationError as exc:
            return PatchApplicationResult(applied=False, diff=patch, error=str(exc))

    def _run_git_apply(self, patch: str, check: bool) -> subprocess.CompletedProcess[str]:
        command = [
            "git",
            "apply",
            "--whitespace=nowarn",
            "--ignore-whitespace",
            "--unidiff-zero",
        ]
        if check:
            command.append("--check")
        return subprocess.run(
            command,
            cwd=self.repo_root,
            input=patch,
            capture_output=True,
            text=True,
            timeout=30,
        )

    @classmethod
    def _extract_patch_paths(cls, patch: str) -> Set[str]:
        paths: Set[str] = set()
        for line in patch.splitlines():
            if not line.startswith("+++ "):
                continue
            raw_path = line[4:].strip().split("\t", 1)[0].split(" ", 1)[0]
            normalized = cls._normalize_patch_header_path(raw_path)
            if normalized:
                paths.add(normalized)
        return paths

    @staticmethod
    def _normalize_patch_text(patch: str) -> str:
        return normalize_unified_diff(patch)

    @staticmethod
    def _normalize_patch_header_path(path: str) -> str:
        if path == "/dev/null":
            return ""
        if path.startswith(("a/", "b/")):
            path = path[2:]
        return path.replace("\\", "/").strip("/")

    @staticmethod
    def _normalize_path(path: str) -> str:
        return Path(path).as_posix().strip("/")
