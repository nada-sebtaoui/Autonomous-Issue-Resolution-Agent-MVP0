"""Docker-based sandbox for applying generated patches and running tests."""

import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .patcher import normalize_unified_diff


PATCH_HELPER = r'''
import re
import sys
from pathlib import Path


class PatchError(Exception):
    pass


def safe_path(repo_root, patch_path):
    if patch_path.startswith(("a/", "b/")):
        patch_path = patch_path[2:]
    path = Path(patch_path)
    if path.is_absolute() or ".." in path.parts:
        raise PatchError(f"unsafe patch path: {patch_path}")
    resolved = (repo_root / path).resolve()
    if repo_root not in resolved.parents and resolved != repo_root:
        raise PatchError(f"patch path escapes repository: {patch_path}")
    return resolved


def parse_target_file(lines):
    for line in lines:
        if line.startswith("+++ "):
            patch_path = line[4:].strip().split("\t", 1)[0].split(" ", 1)[0]
            if patch_path != "/dev/null":
                return patch_path
    raise PatchError("patch does not contain a target file")


def lines_match(actual, expected):
    return actual == expected or actual.strip() == expected.strip()


def apply_patch(repo_root, patch_file):
    lines = patch_file.read_text().splitlines(keepends=True)
    target = safe_path(repo_root, parse_target_file(lines))
    if not target.exists():
        raise PatchError(f"target file does not exist: {target}")

    original = target.read_text().splitlines(keepends=True)
    output = []
    old_index = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line.startswith("@@ "):
            index += 1
            continue

        match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if not match:
            raise PatchError(f"invalid hunk header: {line.strip()}")

        old_start = int(match.group(1)) - 1
        output.extend(original[old_index:old_start])
        old_index = old_start
        index += 1

        while index < len(lines) and not lines[index].startswith("@@ "):
            hunk_line = lines[index]
            if hunk_line.startswith(("diff --git ", "--- ", "+++ ")):
                break
            if hunk_line.startswith("\\ No newline at end of file"):
                index += 1
                continue

            marker = hunk_line[:1]
            content = hunk_line[1:]
            if marker == " ":
                if old_index >= len(original) or not lines_match(original[old_index], content):
                    raise PatchError("patch context does not match target file")
                output.append(original[old_index])
                old_index += 1
            elif marker == "-":
                if old_index >= len(original) or not lines_match(original[old_index], content):
                    raise PatchError("patch removal does not match target file")
                old_index += 1
            elif marker == "+":
                output.append(content)
            else:
                raise PatchError(f"invalid patch line: {hunk_line.rstrip()}")
            index += 1

    output.extend(original[old_index:])
    target.write_text("".join(output))


if __name__ == "__main__":
    try:
        apply_patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    except Exception as exc:
        print(f"Patch application failed: {exc}", file=sys.stderr)
        sys.exit(2)
'''


@dataclass
class DockerSandboxResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    container_name: str = ""
    patch_applied: bool = False
    cleanup_succeeded: bool = True


class DockerSandbox:
    """Runs patch application and tests inside a temporary Docker container."""

    def __init__(
        self,
        image: str = "python:3.11-slim",
        test_command: str = "python -m pytest -q",
        timeout: int = 120,
        memory: Optional[str] = None,
        cpus: Optional[str] = None,
        network_disabled: bool = False,
    ):
        self.image = image
        self.test_command = test_command
        self.timeout = timeout
        self.memory = memory
        self.cpus = cpus
        self.network_disabled = network_disabled

    def run(
        self,
        repo_path: Path,
        patch: str,
        test_command: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> DockerSandboxResult:
        start = time.monotonic()
        container_name = f"ai-issue-agent-{uuid.uuid4().hex[:12]}"
        effective_timeout = timeout or self.timeout
        command = test_command or self.test_command

        try:
            with tempfile.TemporaryDirectory(prefix="agent_sandbox_") as temp_dir:
                sandbox_repo = Path(temp_dir) / "repo"
                self._copy_repo(Path(repo_path), sandbox_repo)
                (sandbox_repo / ".agent_apply_patch.py").write_text(PATCH_HELPER)
                (sandbox_repo / ".agent.patch").write_text(self._normalize_patch_text(patch))

                docker_command = self._docker_command(sandbox_repo, container_name, command)
                try:
                    result = subprocess.run(
                        docker_command,
                        capture_output=True,
                        text=True,
                        timeout=effective_timeout,
                    )
                    duration = time.monotonic() - start
                    patch_applied = "PATCH_APPLIED" in result.stdout
                    return DockerSandboxResult(
                        success=result.returncode == 0,
                        exit_code=result.returncode,
                        stdout=result.stdout[-8000:],
                        stderr=result.stderr[-8000:],
                        duration_seconds=duration,
                        timed_out=False,
                        container_name=container_name,
                        patch_applied=patch_applied,
                    )
                except subprocess.TimeoutExpired as exc:
                    cleanup_succeeded = self._remove_container(container_name)
                    duration = time.monotonic() - start
                    stdout = self._decode_timeout_output(exc.stdout)
                    stderr = self._decode_timeout_output(exc.stderr)
                    return DockerSandboxResult(
                        success=False,
                        exit_code=-1,
                        stdout=stdout[-8000:],
                        stderr=(stderr or "Docker sandbox timed out")[-8000:],
                        duration_seconds=duration,
                        timed_out=True,
                        container_name=container_name,
                        cleanup_succeeded=cleanup_succeeded,
                    )
        except FileNotFoundError:
            duration = time.monotonic() - start
            return DockerSandboxResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="Docker executable not found. Install Docker and ensure it is on PATH.",
                duration_seconds=duration,
                container_name=container_name,
            )

    def _docker_command(self, sandbox_repo: Path, container_name: str, test_command: str) -> list[str]:
        install_command = (
            "python -m pip install -q pytest && "
            "if [ -f requirements.txt ]; then "
            "python -m pip install -q -r requirements.txt; "
            "elif [ -f pyproject.toml ] || [ -f setup.py ]; then "
            "python -m pip install -q -e .; "
            "fi"
        )
        container_script = (
            "python .agent_apply_patch.py /work /work/.agent.patch && "
            "echo PATCH_APPLIED && "
            f"{install_command} && "
            f"{test_command}"
        )

        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "-v",
            f"{sandbox_repo.as_posix()}:/work",
            "-w",
            "/work",
        ]
        if self.memory:
            command.extend(["--memory", self.memory])
        if self.cpus:
            command.extend(["--cpus", self.cpus])
        if self.network_disabled:
            command.extend(["--network", "none"])

        command.extend([self.image, "sh", "-lc", container_script])
        return command

    @staticmethod
    def _copy_repo(source: Path, destination: Path) -> None:
        ignore = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".mypy_cache")
        shutil.copytree(source, destination, ignore=ignore)

    @staticmethod
    def _normalize_patch_text(patch: str) -> str:
        return normalize_unified_diff(patch)

    @staticmethod
    def _decode_timeout_output(output) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode(errors="ignore")
        return str(output)

    @staticmethod
    def _remove_container(container_name: str) -> bool:
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return True
        except Exception:
            return False
