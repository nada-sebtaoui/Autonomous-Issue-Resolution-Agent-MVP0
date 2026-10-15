"""Small browser UI for running the existing AI GitHub Issue Agent.

This intentionally uses only the Python standard library so the project stays
easy to run: `python web_app.py`, then open http://127.0.0.1:8000.
"""

from __future__ import annotations

import json
import re
import threading
import traceback
import uuid
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from src.agent import IssueResolutionAgent
from src.config import Config


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

STAGES = [
    ("fetch_issue", "Fetching GitHub issue"),
    ("clone_repo", "Preparing repository"),
    ("retrieve", "Finding relevant files"),
    ("plan", "Analyzing repository"),
    ("propose_fix", "Generating fix"),
    ("apply_patch", "Applying patch"),
    ("run_tests", "Running tests"),
]


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, payload: dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "status": "queued",
                "stage": None,
                "stages": self._initial_stages(),
                "logs": ["[INFO] Run queued"],
                "result": None,
                "error": None,
                "request": {
                    "repo": payload["repo"],
                    "issue": payload["issue"],
                    "applyFix": payload.get("applyFix", False),
                    "useDocker": payload.get("useDocker", False),
                },
            }
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return json.loads(json.dumps(job)) if job else None

    def update(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(updates)

    def log(self, job_id: str, level: str, message: str) -> None:
        with self._lock:
            self._jobs[job_id]["logs"].append(f"[{level}] {message}")

    def set_stage(self, job_id: str, stage_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "running"
            job["stage"] = stage_id
            seen_current = False
            for stage in job["stages"]:
                if stage["id"] == stage_id:
                    stage["status"] = "active"
                    seen_current = True
                elif not seen_current:
                    stage["status"] = "completed"
                elif stage["status"] == "active":
                    stage["status"] = "pending"
            job["logs"].append(f"[INFO] {message}")

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for stage in job["stages"]:
                if stage["status"] == "active":
                    stage["status"] = "completed"
            job.update(status="completed", stage=None, result=result)
            job["logs"].append("[SUCCESS] Agent completed")

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for stage in job["stages"]:
                if stage["status"] == "active":
                    stage["status"] = "failed"
            job.update(status="failed", stage=None, error=error)
            job["logs"].append(f"[ERROR] {error}")

    @staticmethod
    def _initial_stages() -> list[dict[str, str]]:
        return [{"id": stage_id, "label": label, "status": "pending"} for stage_id, label in STAGES]


jobs = JobStore()


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def summarize_tests(test_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not test_result:
        return None

    output = f"{test_result.get('stdout', '')}\n{test_result.get('stderr', '')}"
    passed = re.search(r"(\d+)\s+passed", output)
    failed = re.search(r"(\d+)\s+failed", output)
    return {
        "passed": bool(test_result.get("passed")),
        "passedCount": int(passed.group(1)) if passed else None,
        "failedCount": int(failed.group(1)) if failed else 0 if test_result.get("passed") else None,
        "output": output.strip(),
    }


def serialize_result(result: Any) -> dict[str, Any]:
    data = to_jsonable(result)
    proposal = data.get("proposal") or {}
    target_file = proposal.get("target_file") or proposal.get("file") or ""
    patch = proposal.get("patch") or ""

    return {
        "issue": data.get("issue"),
        "candidateFiles": data.get("candidate_files", []),
        "plan": data.get("plan"),
        "proposal": proposal,
        "targetFile": target_file,
        "patch": patch,
        "patchResult": data.get("patch_result"),
        "sandboxResult": data.get("sandbox_result"),
        "tests": summarize_tests(data.get("test_result")),
        "applied": data.get("applied", False),
    }


def validate_payload(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    token = str(payload.get("token", "")).strip()
    repo = str(payload.get("repo", "")).strip()

    try:
        issue = int(payload.get("issue"))
    except (TypeError, ValueError):
        return None, "Issue number must be a positive integer."

    if not token:
        return None, "GitHub token is required."
    if not REPO_PATTERN.match(repo):
        return None, "Repository must use the owner/repository format."
    if issue < 1:
        return None, "Issue number must be a positive integer."

    return {
        "token": token,
        "repo": repo,
        "issue": issue,
        "localRepoPath": str(payload.get("localRepoPath", "")).strip() or None,
        "applyFix": bool(payload.get("applyFix", False)),
        "useDocker": bool(payload.get("useDocker", False)),
    }, None


def run_agent(job_id: str, payload: dict[str, Any]) -> None:
    try:
        jobs.update(job_id, status="running")
        config = Config.from_env(override_dotenv=True)
        config.github_token = payload["token"]
        jobs.log(
            job_id,
            "INFO",
            f"Using {config.groq_model_a} at {config.groq_base_url} "
            f"(fallback {config.groq_model_b})",
        )

        def progress(stage: str, message: str) -> None:
            if stage in {stage_id for stage_id, _ in STAGES}:
                jobs.set_stage(job_id, stage, message)
            else:
                jobs.log(job_id, "INFO", message)

        agent = IssueResolutionAgent(config)
        result = agent.run(
            payload["repo"],
            payload["issue"],
            apply_fix=payload["applyFix"],
            use_docker=payload["useDocker"],
            local_repo_path=payload["localRepoPath"],
            progress_callback=progress,
        )
        jobs.complete(job_id, serialize_result(result))
    except Exception as exc:  # noqa: BLE001 - convert local run failures into UI output.
        traceback.print_exc()
        jobs.fail(job_id, str(exc))


class Handler(BaseHTTPRequestHandler):
    server_version = "AIIssueAgentUI/1.0"

    def do_GET(self) -> None:
        if self.path.startswith("/api/runs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            job = jobs.get(job_id)
            if not job:
                self.write_json({"error": "Run not found."}, HTTPStatus.NOT_FOUND)
                return
            self.write_json(job)
            return

        route = self.path.split("?", 1)[0]
        if route == "/":
            route = "/index.html"
        self.serve_static(route)

    def do_POST(self) -> None:
        if self.path != "/api/runs":
            self.write_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.write_json({"error": "Request body must be valid JSON."}, HTTPStatus.BAD_REQUEST)
            return

        validated, error = validate_payload(payload)
        if error:
            self.write_json({"error": error}, HTTPStatus.BAD_REQUEST)
            return

        job_id = jobs.create(validated)
        thread = threading.Thread(target=run_agent, args=(job_id, validated), daemon=True)
        thread.start()
        self.write_json({"id": job_id}, HTTPStatus.ACCEPTED)

    def serve_static(self, route: str) -> None:
        file_path = (WEB_DIR / route.lstrip("/")).resolve()
        if WEB_DIR not in file_path.parents and file_path != WEB_DIR:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_types.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # Keep access logs compact and free of request bodies/secrets.
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"AI GitHub Issue Agent UI running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
