"""Orchestrates the MVP pipeline:

Issue -> repo exploration -> LLM reasoning -> proposed fix -> tests
"""

from dataclasses import dataclass
from typing import List, Optional

from .config import Config
from .docker_sandbox import DockerSandbox, DockerSandboxResult
from .github_client import GitHubClient
from .llm_planner import LLMPlanner
from .patcher import PatchApplicationResult, PatchManager, PatchValidationError
from .retrieval import CodeRetriever, RetrievalResult
from .test_runner import TestRunner


@dataclass
class RunResult:
    issue: dict
    candidate_files: List[RetrievalResult]
    plan: dict
    proposal: dict
    patch_result: Optional[PatchApplicationResult] = None
    sandbox_result: Optional[DockerSandboxResult] = None
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

    def run(
        self,
        repo: str,
        issue_number: int,
        apply_fix: bool = False,
        use_docker: bool = False,
    ) -> RunResult:
        issue = self.github.fetch_issue(repo, issue_number)
        repo_path = self.github.clone_repo(repo)

        retriever = CodeRetriever(
            repo_path,
            lexical_weight=self.config.retrieval_lexical_weight,
            semantic_weight=self.config.retrieval_semantic_weight,
        )
        candidates = retriever.retrieve(
            issue["title"],
            issue["body"],
            top_k=self.config.retrieval_top_k,
            mode=self.config.retrieval_mode,
        )

        plan = self.planner.plan_fix(issue, candidates)
        proposal = self.planner.propose_fix(issue, candidates, plan=plan)

        patch_result = None
        sandbox_result = None
        test_result = None
        applied = False
        if apply_fix and proposal.get("target_file") and proposal.get("patch"):
            patch_manager = PatchManager(repo_path)
            if use_docker:
                try:
                    patch_manager.validate_patch(proposal["target_file"], proposal["patch"])
                    patch_result = PatchApplicationResult(applied=True, diff=proposal["patch"])
                    sandbox = DockerSandbox(
                        image=self.config.docker_image,
                        test_command=self.config.docker_test_command,
                        timeout=self.config.docker_timeout,
                        memory=self.config.docker_memory or None,
                        cpus=self.config.docker_cpus or None,
                        network_disabled=self.config.docker_network_disabled,
                    )
                    sandbox_result = sandbox.run(
                        repo_path=repo_path,
                        patch=proposal["patch"],
                        test_command=self.config.docker_test_command,
                        timeout=self.config.docker_timeout,
                    )
                    test_result = {
                        "passed": sandbox_result.success,
                        "returncode": sandbox_result.exit_code,
                        "stdout": sandbox_result.stdout,
                        "stderr": sandbox_result.stderr,
                        "timed_out": sandbox_result.timed_out,
                        "duration_seconds": sandbox_result.duration_seconds,
                    }
                    applied = sandbox_result.success
                except PatchValidationError as exc:
                    patch_result = PatchApplicationResult(
                        applied=False, diff=proposal["patch"], error=str(exc)
                    )
            else:
                patch_result = patch_manager.apply_patch(
                    proposal["target_file"], proposal["patch"]
                )
                applied = patch_result.applied
                if applied:
                    test_result = TestRunner(repo_path).run()

        return RunResult(
            issue=issue,
            candidate_files=candidates,
            plan=plan,
            proposal=proposal,
            patch_result=patch_result,
            sandbox_result=sandbox_result,
            test_result=test_result,
            applied=applied,
        )
