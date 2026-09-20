"""CLI entrypoint for the AI GitHub Issue Resolution Agent (MVP).

Usage:
    python main.py --repo owner/name --issue 17
    python main.py --repo owner/name --issue 17 --apply   # write fix + run tests
    python main.py --repo owner/name --issue 17 --apply --docker
"""

import argparse
import json
import sys

from src.agent import IssueResolutionAgent
from src.config import Config


def main() -> int:
    parser = argparse.ArgumentParser(description="AI GitHub Issue Resolution Agent (MVP)")
    parser.add_argument("--repo", required=True, help="owner/name, e.g. octocat/Hello-World")
    parser.add_argument("--issue", required=True, type=int, help="Issue number")
    parser.add_argument("--apply", action="store_true", help="Write the proposed fix to disk and run tests")
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Run patch validation/tests inside an isolated Docker sandbox",
    )
    args = parser.parse_args()

    config = Config.from_env()
    agent = IssueResolutionAgent(config)

    print(f"Fetching issue #{args.issue} from {args.repo}...")
    result = agent.run(args.repo, args.issue, apply_fix=args.apply, use_docker=args.docker)

    print("\n=== Issue ===")
    print(f"#{result.issue['number']}: {result.issue['title']}")

    print(f"\n=== Candidate files ({len(result.candidate_files)}) ===")
    for f in result.candidate_files:
        path = getattr(f, "relative_path", str(f.path))
        reason = getattr(f, "reason", "")
        print(f"  score={f.score:.3f}  {path}")
        if reason:
            print(f"    {reason}")

    print("\n=== Implementation plan ===")
    print(json.dumps(result.plan, indent=2))

    print("\n=== Proposed fix ===")
    print(json.dumps({k: v for k, v in result.proposal.items() if k != "patch"}, indent=2))

    if result.proposal.get("patch"):
        print("\n=== Proposed patch ===")
        print(result.proposal["patch"])

    if result.patch_result and not result.patch_result.applied:
        print("\n=== Patch: FAIL ===")
        print(result.patch_result.error)

    if result.sandbox_result:
        sandbox_status = "SUCCESS" if result.sandbox_result.success else "FAIL"
        print(f"\n=== Docker sandbox: {sandbox_status} ===")
        print(f"Patch applied inside sandbox: {result.sandbox_result.patch_applied}")
        print(f"Timed out: {result.sandbox_result.timed_out}")
        print(f"Duration: {result.sandbox_result.duration_seconds:.2f}s")
        print(f"Sandbox cleaned up: {result.sandbox_result.cleanup_succeeded}")
        if result.sandbox_result.stderr:
            print(result.sandbox_result.stderr[-1000:])

    if result.test_result:
        status = "PASS" if result.test_result["passed"] else "FAIL"
        print(f"\n=== Tests: {status} ===")
        print(result.test_result["stdout"][-1000:])

    return 0


if __name__ == "__main__":
    sys.exit(main())
