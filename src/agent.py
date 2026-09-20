"""Orchestrates the MVP pipeline:

Issue -> repo exploration -> LLM reasoning -> proposed fix -> tests
"""

from dataclasses import dataclass
from typing import List, Optional

from .config import Config
from .github_client import GitHubClient
from .llm_planner import LLMPlanner
from .repo_explorer import RepoExplorer, ScoredFile
from .test_runner import TestRunner


@dataclass
class RunResult:
    issue: dict
    candidate_files: List[ScoredFile]
    proposal: dict
    test_result: Optional[dict] = None
    applied: bool = False


class IssueResolutionAgent:
    def __init__(self, config: Config):
        self.config = config
        self.github = GitHubClient(token=config.github_token)
        self.planner = LLMPlanner(
            api_key=config.groq_api_key,
            base_url=config.groq_base_url,
            model=config.groq_model_a,
            fallback_model=config.groq_model_b,
            skip_temperature=config.groq_skip_temperature,
        )

    def run(self, repo: str, issue_number: int, apply_fix: bool = False) -> RunResult:
        issue = self.github.fetch_issue(repo, issue_number)
        repo_path = self.github.clone_repo(repo)

        explorer = RepoExplorer(repo_path)
        candidates = explorer.find_relevant_files(
            issue["title"], issue["body"], top_k=self.config.max_files_to_inspect
        )

        proposal = self.planner.propose_fix(issue, candidates)

        test_result = None
        applied = False
        if apply_fix and proposal.get("target_file"):
            target = repo_path / proposal["target_file"]
            if target.exists():
                target.write_text(proposal["new_file_content"])
                applied = True
                test_result = TestRunner(repo_path).run()

        return RunResult(
            issue=issue,
            candidate_files=candidates,
            proposal=proposal,
            test_result=test_result,
            applied=applied,
        )
