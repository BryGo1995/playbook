# state.py
import json
import os
from datetime import datetime, timezone


class StateManager:
    """Manages agent state in a local JSON file."""

    def __init__(self, base_dir: str = os.path.expanduser("~/.agent-orchestrator")):
        self.base_dir = base_dir
        self.state_file = os.path.join(base_dir, "state.json")
        self.logs_dir = os.path.join(base_dir, "logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        self.agents = self._load()

    def _load(self) -> list[dict]:
        if not os.path.exists(self.state_file):
            return []
        with open(self.state_file) as f:
            data = json.load(f)
        return data.get("agents", [])

    def _save(self):
        os.makedirs(self.base_dir, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump({"agents": self.agents}, f, indent=2)

    def add_agent(
        self,
        pid: int,
        issue: str,
        repo: str,
        agent_type: str,
        timeout_minutes: int,
        attempt: int,
        project_item_id: str | None = None,
    ):
        self.agents.append(
            {
                "pid": pid,
                "issue": issue,
                "repo": repo,
                "type": agent_type,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "timeout_minutes": timeout_minutes,
                "attempt": attempt,
                "project_item_id": project_item_id,
            }
        )
        self._save()

    def remove_agent(self, pid: int):
        self.agents = [a for a in self.agents if a["pid"] != pid]
        self._save()

    def get_agents_by_type(self, agent_type: str) -> list[dict]:
        return [a for a in self.agents if a["type"] == agent_type]

    def is_issue_active(self, issue: str) -> bool:
        return any(a["issue"] == issue for a in self.agents)

    def log_path(self, repo: str, issue_number: int) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe_repo = repo.replace("/", "-")
        return os.path.join(self.logs_dir, f"{safe_repo}-{issue_number}-{timestamp}.json")
