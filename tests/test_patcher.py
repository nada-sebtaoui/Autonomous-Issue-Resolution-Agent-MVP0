import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from src.llm_planner import LLMOutputError, LLMPlanner
from src.patcher import PatchManager, PatchValidationError


def test_apply_valid_patch(tmp_path):
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text('def value():\n    return "old"\n')

    patch = """diff --git a/src/example.py b/src/example.py
--- a/src/example.py
+++ b/src/example.py
@@ -1,2 +1,2 @@
 def value():
-    return "old"
+    return "new"
"""

    result = PatchManager(tmp_path).apply_patch("src/example.py", patch)

    assert result.applied
    assert target.read_text() == 'def value():\n    return "new"\n'


def test_rejects_invalid_patch(tmp_path):
    target = tmp_path / "example.py"
    target.write_text("print('hello')\n")

    result = PatchManager(tmp_path).apply_patch("example.py", "not a patch")

    assert not result.applied
    assert "target file" in result.error


def test_rejects_nonexistent_target_file(tmp_path):
    patch = """diff --git a/missing.py b/missing.py
--- a/missing.py
+++ b/missing.py
@@ -1 +1 @@
-old
+new
"""

    result = PatchManager(tmp_path).apply_patch("missing.py", patch)

    assert not result.applied
    assert "does not exist" in result.error


def test_rejects_path_traversal(tmp_path):
    with pytest.raises(PatchValidationError):
        PatchManager(tmp_path).validate_target_file("../outside.py")


def test_rejects_patch_that_cannot_be_applied(tmp_path):
    target = tmp_path / "example.py"
    target.write_text("actual\n")
    patch = """diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-expected
+changed
"""

    result = PatchManager(tmp_path).apply_patch("example.py", patch)

    assert not result.applied
    assert "patch cannot be applied" in result.error


def test_validate_llm_patch_proposal():
    proposal = LLMPlanner._validate_proposal(
        {
            "target_file": "src/example.py",
            "explanation": "Fix the bug.",
            "patch": (
                "diff --git a/src/example.py b/src/example.py\n"
                "--- a/src/example.py\n"
                "+++ b/src/example.py\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            ),
            "tests_to_run": ["pytest tests/test_example.py"],
        }
    )

    assert proposal["target_file"] == "src/example.py"
    assert proposal["tests_to_run"] == ["pytest tests/test_example.py"]


def test_rejects_llm_output_missing_patch():
    with pytest.raises(LLMOutputError):
        LLMPlanner._validate_proposal(
            {
                "target_file": "src/example.py",
                "explanation": "Fix the bug.",
            }
        )


def test_rejects_llm_output_apply_patch_format():
    with pytest.raises(LLMOutputError):
        LLMPlanner._validate_proposal(
            {
                "target_file": "calculator.py",
                "explanation": "Fix multiplication.",
                "patch": "*** Begin Patch\n*** Update File: calculator.py\n*** End Patch\n",
                "tests_to_run": ["pytest"],
            }
        )


def test_validate_llm_plan():
    plan = LLMPlanner._validate_plan(
        {
            "summary": "Login fails for missing email.",
            "root_cause": "Input validation is missing.",
            "files_to_modify": [{"path": "src/auth.py", "reason": "login handler lives here"}],
            "implementation_steps": ["Validate email before use"],
            "tests_to_run": ["pytest tests/test_auth.py"],
            "risks": ["May need to preserve existing error shape"],
        }
    )

    assert plan["files_to_modify"][0]["path"] == "src/auth.py"
    assert plan["implementation_steps"] == ["Validate email before use"]


def test_rejects_llm_plan_missing_fields():
    with pytest.raises(LLMOutputError):
        LLMPlanner._validate_plan(
            {
                "summary": "Missing required fields.",
                "root_cause": "Unknown.",
            }
        )
