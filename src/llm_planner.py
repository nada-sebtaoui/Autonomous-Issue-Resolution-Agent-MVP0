"""LLM planning and patch generation for issue resolution."""

import json
import re
from typing import FrozenSet, List, Optional

from openai import APIError, OpenAI


class LLMOutputError(ValueError):
    """Raised when the model returns JSON with the wrong shape."""


PLANNING_PROMPT = """You are an AI software engineering agent. You are given a GitHub \
issue and retrieved code context. Your job is to investigate the issue and create a plan.

Respond with ONLY a JSON object, no markdown fences, no commentary, in this exact shape:
{
  "summary": "short problem summary",
  "root_cause": "most likely root cause hypothesis",
  "files_to_modify": [
    {"path": "relative/path.py", "reason": "why this file likely needs changes"}
  ],
  "implementation_steps": ["step 1", "step 2"],
  "tests_to_run": ["pytest tests/test_relevant.py"],
  "risks": ["risk or edge case"]
}
If there is not enough code context to make a change, return empty files_to_modify and explain why.
"""


PATCH_PROMPT = """You are an AI software engineering agent. You are given a GitHub \
issue, retrieved code context, and an implementation plan. Your job is to:

1. Identify which single file most likely needs to change to fix the issue.
2. Propose a minimal unified diff patch for that file.
3. Briefly explain the bug and the fix.

Respond with ONLY a JSON object, no markdown fences, no commentary, in this exact shape:
{
  "target_file": "relative/path/to/file.py",
  "explanation": "short explanation of the bug and the fix",
  "patch": "git unified diff that modifies only target_file",
  "tests_to_run": ["pytest tests/test_relevant.py"]
}
The patch MUST be a standard unified diff with `diff --git`, `--- a/...`, `+++ b/...`,
and line-numbered hunk headers like `@@ -1,4 +1,4 @@`. Do NOT return Cursor/ApplyPatch
format. Do NOT use `*** Begin Patch`, `*** Update File`, or `*** End Patch`.
If none of the candidate files look relevant, set target_file and patch to null and use \
explanation to say why.
"""


class LLMPlanner:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        fallback_model: Optional[str] = None,
        skip_temperature: Optional[FrozenSet[str]] = None,
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.fallback_model = fallback_model if fallback_model and fallback_model != model else None
        self.skip_temperature = skip_temperature or frozenset()

    def _chat_kwargs(self, model: str, messages: list) -> dict:
        kwargs = {
            "model": model,
            "messages": messages,
            "max_tokens": 4096,
        }
        if model not in self.skip_temperature:
            kwargs["temperature"] = 0
        return kwargs

    def plan_fix(self, issue: dict, candidate_files: List[object]) -> dict:
        context_block = self._format_context(candidate_files)
        user_prompt = (
            f"GitHub Issue #{issue['number']}: {issue['title']}\n\n"
            f"{issue['body']}\n\n"
            f"Relevant code context:\n\n{context_block}"
        )
        messages = [
            {"role": "system", "content": PLANNING_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        return self._complete_json(messages, self._validate_plan)

    def propose_fix(
        self,
        issue: dict,
        candidate_files: List[object],
        plan: Optional[dict] = None,
    ) -> dict:
        context_block = self._format_context(candidate_files)
        plan_block = json.dumps(plan or {}, indent=2)
        user_prompt = (
            f"GitHub Issue #{issue['number']}: {issue['title']}\n\n"
            f"{issue['body']}\n\n"
            f"Implementation plan:\n{plan_block}\n\n"
            f"Relevant code context:\n\n{context_block}"
        )
        messages = [
            {"role": "system", "content": PATCH_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        return self._complete_json(messages, self._validate_proposal)

    def _complete_json(self, messages: list, validator) -> dict:
        models = [self.model]
        if self.fallback_model:
            models.append(self.fallback_model)

        last_error: Optional[Exception] = None
        for model in models:
            try:
                response = self.client.chat.completions.create(
                    **self._chat_kwargs(model, messages)
                )
                text = response.choices[0].message.content or ""
                return validator(self._parse_json(text))
            except (json.JSONDecodeError, APIError, LLMOutputError) as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise RuntimeError("LLM planner produced no response")

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                return json.loads(text[start : end + 1])
            raise

    @staticmethod
    def _validate_proposal(proposal: dict) -> dict:
        if not isinstance(proposal, dict):
            raise LLMOutputError("LLM response must be a JSON object")

        for field in ("target_file", "explanation", "patch"):
            if field not in proposal:
                raise LLMOutputError(f"LLM response is missing required field: {field}")

        if "tests_to_run" not in proposal:
            proposal["tests_to_run"] = []

        if proposal["target_file"] is None:
            proposal["patch"] = None
            return proposal

        if not isinstance(proposal["target_file"], str) or not proposal["target_file"].strip():
            raise LLMOutputError("target_file must be a non-empty string or null")
        if not isinstance(proposal["explanation"], str):
            raise LLMOutputError("explanation must be a string")
        if not isinstance(proposal["patch"], str) or not proposal["patch"].strip():
            raise LLMOutputError("patch must be a non-empty string when target_file is set")
        patch = proposal["patch"].lstrip()
        if patch.startswith("*** Begin Patch"):
            raise LLMOutputError("patch must be a unified diff, not Cursor ApplyPatch format")
        if "diff --git " not in patch or "--- " not in patch or "+++ " not in patch or "@@" not in patch:
            raise LLMOutputError("patch must be a valid-looking git unified diff")
        if not re.search(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", patch, re.MULTILINE):
            raise LLMOutputError("patch hunk headers must include line numbers")
        if not isinstance(proposal["tests_to_run"], list) or not all(
            isinstance(item, str) for item in proposal["tests_to_run"]
        ):
            raise LLMOutputError("tests_to_run must be a list of strings")

        return proposal

    @staticmethod
    def _validate_plan(plan: dict) -> dict:
        if not isinstance(plan, dict):
            raise LLMOutputError("LLM plan must be a JSON object")

        required_fields = (
            "summary",
            "root_cause",
            "files_to_modify",
            "implementation_steps",
            "tests_to_run",
            "risks",
        )
        for field in required_fields:
            if field not in plan:
                raise LLMOutputError(f"LLM plan is missing required field: {field}")

        if not isinstance(plan["summary"], str):
            raise LLMOutputError("summary must be a string")
        if not isinstance(plan["root_cause"], str):
            raise LLMOutputError("root_cause must be a string")
        if not isinstance(plan["files_to_modify"], list):
            raise LLMOutputError("files_to_modify must be a list")
        for item in plan["files_to_modify"]:
            if not isinstance(item, dict) or "path" not in item or "reason" not in item:
                raise LLMOutputError("files_to_modify items must include path and reason")
        if not isinstance(plan["implementation_steps"], list) or not all(
            isinstance(item, str) for item in plan["implementation_steps"]
        ):
            raise LLMOutputError("implementation_steps must be a list of strings")
        if not isinstance(plan["tests_to_run"], list) or not all(
            isinstance(item, str) for item in plan["tests_to_run"]
        ):
            raise LLMOutputError("tests_to_run must be a list of strings")
        if not isinstance(plan["risks"], list) or not all(
            isinstance(item, str) for item in plan["risks"]
        ):
            raise LLMOutputError("risks must be a list of strings")

        return plan

    @staticmethod
    def _format_context(candidate_files: List[object]) -> str:
        return "\n\n".join(LLMPlanner._format_candidate(candidate) for candidate in candidate_files)

    @staticmethod
    def _format_candidate(candidate: object) -> str:
        path = getattr(candidate, "relative_path", None) or str(getattr(candidate, "path"))
        snippet = getattr(candidate, "snippet", "")
        reason = getattr(candidate, "reason", "")
        symbol = getattr(candidate, "symbol", "")
        start_line = getattr(candidate, "start_line", None)
        end_line = getattr(candidate, "end_line", None)
        score = getattr(candidate, "score", None)

        metadata = []
        if symbol:
            metadata.append(f"symbol={symbol}")
        if start_line and end_line:
            metadata.append(f"lines={start_line}-{end_line}")
        if score is not None:
            metadata.append(f"score={score:.3f}")
        if reason:
            metadata.append(f"reason={reason}")

        metadata_block = "\n".join(f"- {item}" for item in metadata)
        return f"### {path}\n{metadata_block}\n```\n{snippet}\n```"
