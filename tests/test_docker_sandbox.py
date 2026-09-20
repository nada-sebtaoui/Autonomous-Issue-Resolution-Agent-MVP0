import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.docker_sandbox import DockerSandbox


def test_docker_sandbox_success(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("def add(a, b): return a + b\n")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "PATCH_APPLIED\n1 passed\n", "")

    monkeypatch.setattr("src.docker_sandbox.subprocess.run", fake_run)

    result = DockerSandbox().run(tmp_path, "diff --git a/app.py b/app.py\n")

    assert result.success
    assert result.exit_code == 0
    assert result.patch_applied
    assert "1 passed" in result.stdout
    assert calls[0][0:3] == ["docker", "run", "--rm"]


def test_docker_sandbox_failure_captures_stdout_stderr(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("def add(a, b): return a + b\n")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "PATCH_APPLIED\nfailed output\n", "boom\n")

    monkeypatch.setattr("src.docker_sandbox.subprocess.run", fake_run)

    result = DockerSandbox().run(tmp_path, "diff --git a/app.py b/app.py\n")

    assert not result.success
    assert result.exit_code == 1
    assert result.patch_applied
    assert "failed output" in result.stdout
    assert "boom" in result.stderr


def test_docker_sandbox_timeout_removes_container(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("def add(a, b): return a + b\n")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["docker", "rm"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise subprocess.TimeoutExpired(command, timeout=1, output="partial", stderr="timeout")

    monkeypatch.setattr("src.docker_sandbox.subprocess.run", fake_run)

    result = DockerSandbox(timeout=1).run(tmp_path, "diff --git a/app.py b/app.py\n")

    assert not result.success
    assert result.timed_out
    assert result.exit_code == -1
    assert result.cleanup_succeeded
    assert any(command[:3] == ["docker", "rm", "-f"] for command in commands)


def test_docker_sandbox_handles_docker_unavailable(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("def add(a, b): return a + b\n")

    def fake_run(command, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("src.docker_sandbox.subprocess.run", fake_run)

    result = DockerSandbox().run(tmp_path, "diff --git a/app.py b/app.py\n")

    assert not result.success
    assert result.exit_code == -1
    assert "Docker executable not found" in result.stderr


def test_docker_sandbox_includes_resource_controls(monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("def add(a, b): return a + b\n")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, "PATCH_APPLIED\n", "")

    monkeypatch.setattr("src.docker_sandbox.subprocess.run", fake_run)

    DockerSandbox(memory="256m", cpus="0.5", network_disabled=True).run(
        tmp_path, "diff --git a/app.py b/app.py\n"
    )

    command = captured["command"]
    assert "--memory" in command
    assert "256m" in command
    assert "--cpus" in command
    assert "0.5" in command
    assert "--network" in command
    assert "none" in command
