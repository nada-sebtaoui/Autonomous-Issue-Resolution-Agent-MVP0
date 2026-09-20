"""Runs the target repo's test suite and reports pass/fail.

MVP assumption: Python project using pytest. Level 2 adds detection for
package.json / go.mod / etc. so the right test command is picked
automatically.
"""

import subprocess
from pathlib import Path


class TestRunner:
    __test__ = False  # tell pytest this isn't a test class despite the name

    def __init__(self, repo_root: Path, timeout: int = 120):
        self.repo_root = Path(repo_root)
        self.timeout = timeout

    def run(self) -> dict:
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "-q"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return {
                "passed": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "returncode": -1, "stdout": "", "stderr": "Test run timed out"}
        except FileNotFoundError:
            return {"passed": False, "returncode": -1, "stdout": "", "stderr": "pytest not found"}
