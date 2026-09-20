"""CLI entrypoint for the AI GitHub Issue Resolution Agent (MVP).

Usage:
    python main.py --repo owner/name --issue 17
    python main.py --repo owner/name --issue 17 --apply   # write fix + run tests
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
    args = parser.parse_args()

    config = Config.from_env()
    agent = IssueResolutionAgent(config)

    print(f"Fetching issue #{args.issue} from {args.repo}...")
    result = agent.run(args.repo, args.issue, apply_fix=args.apply)

    print("\n=== Issue ===")
    print(f"#{result.issue['number']}: {result.issue['title']}")

    print(f"\n=== Candidate files ({len(result.candidate_files)}) ===")
    for f in result.candidate_files:
        print(f"  score={f.score:<4} {f.path}")

    print("\n=== Proposed fix ===")
    print(json.dumps({k: v for k, v in result.proposal.items() if k != "new_file_content"}, indent=2))

    if result.test_result:
        status = "PASS" if result.test_result["passed"] else "FAIL"
        print(f"\n=== Tests: {status} ===")
        print(result.test_result["stdout"][-1000:])

    return 0


if __name__ == "__main__":
    sys.exit(main())
