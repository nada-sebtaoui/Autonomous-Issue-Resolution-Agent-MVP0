"""LLM reasoning step: given an issue + candidate files, propose a fix.

MVP scope: single-file fixes only, returned as full replacement content
(simplest thing that produces a working end-to-end demo). Level 2 upgrades
this to multi-file unified diffs so `git diff` / PR generation works
cleanly on larger changes.
"""

import json
from typing import FrozenSet, List, Optional

from openai import APIError, OpenAI

from .repo_explorer import ScoredFile

SYSTEM_PROMPT = """You are an AI software engineering agent. You are given a GitHub \
issue and a set of candidate source files from the repository. Your job is to:

1. Identify which single file most likely needs to change to fix the issue.
2. Propose the FULL new content of that file with the fix applied.
3. Briefly explain the bug and the fix.

Respond with ONLY a JSON object, no markdown fences, no commentary, in this exact shape:
{
  "target_file": "relative/path/to/file.py",
  "explanation": "short explanation of the bug and the fix",
  "new_file_content": "the complete new file content"
}
If none of the candidate files look relevant, set target_file and new_file_content to null \
and use explanation to say why.
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

    def propose_fix(self, issue: dict, candidate_files: List[ScoredFile]) -> dict:
        files_block = "\n\n".join(
            f"### {f.path}\n```\n{f.path.read_text(errors='ignore')}\n```" for f in candidate_files
        )
        user_prompt = (
            f"GitHub Issue #{issue['number']}: {issue['title']}\n\n"
            f"{issue['body']}\n\n"
            f"Candidate files:\n\n{files_block}"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

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
                return self._parse_json(text)
            except (json.JSONDecodeError, APIError) as exc:
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
