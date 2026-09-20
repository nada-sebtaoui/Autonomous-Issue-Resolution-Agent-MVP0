"""Minimal GitHub integration: fetch an issue, clone the target repo."""

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import requests


class GitHubClient:
    """Thin wrapper around the GitHub REST API + git CLI for cloning."""

    API_ROOT = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        self.token = token
        self._headers = {"Accept": "application/vnd.github+json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def fetch_issue(self, repo: str, issue_number: int) -> dict:
        """repo is 'owner/name'. Returns title/body/url/labels for the issue."""
        url = f"{self.API_ROOT}/repos/{repo}/issues/{issue_number}"
        resp = requests.get(url, headers=self._headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {
            "number": data["number"],
            "title": data["title"],
            "body": data.get("body") or "",
            "url": data["html_url"],
            "labels": [label["name"] for label in data.get("labels", [])],
        }

    def clone_repo(self, repo: str, dest_dir: Optional[str] = None) -> Path:
        """Shallow-clones `repo` (owner/name) and returns the local checkout path."""
        dest = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="agent_repo_"))
        if dest.exists() and any(dest.iterdir()):
            return dest  # already cloned, reuse it

        clone_url = f"https://github.com/{repo}.git"
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
        return dest
