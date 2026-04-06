# github_client.py
import os
import requests

ORCHESTRATOR_TAG = "[agent-orchestrator]"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"


class GitHubClient:
    """Wraps GitHub GraphQL + REST APIs for project status management and issue operations."""

    def __init__(self, token: str | None = None):
        self.token = token or os.environ["GITHUB_TOKEN"]
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        # Cache for project metadata (populated on first query)
        self._project_id = None
        self._status_field_id = None
        self._status_option_ids = {}

    def _graphql(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query and return the data."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = requests.post(GITHUB_GRAPHQL_URL, json=payload, headers=self.headers, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if "errors" in result:
            raise RuntimeError(f"GraphQL error: {result['errors']}")
        return result["data"]

    def _rest_get(self, path: str) -> dict:
        """Execute a REST API GET request."""
        resp = requests.get(f"https://api.github.com{path}", headers=self.headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _rest_post(self, path: str, json: dict) -> dict:
        """Execute a REST API POST request."""
        resp = requests.post(f"https://api.github.com{path}", json=json, headers=self.headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # --- Project metadata ---

    def load_project_metadata(self, owner: str, project_number: int, status_field_id: str):
        """Load project ID and status option IDs. Call once at startup."""
        data = self._graphql(
            """
            query($owner: String!, $number: Int!) {
                user(login: $owner) {
                    projectV2(number: $number) {
                        id
                    }
                }
            }
            """,
            {"owner": owner, "number": project_number},
        )
        self._project_id = data["user"]["projectV2"]["id"]
        self._status_field_id = status_field_id

        # Load status option IDs
        data = self._graphql(
            """
            query($projectId: ID!) {
                node(id: $projectId) {
                    ... on ProjectV2 {
                        field(name: "Status") {
                            ... on ProjectV2SingleSelectField {
                                options {
                                    id
                                    name
                                }
                            }
                        }
                    }
                }
            }
            """,
            {"projectId": self._project_id},
        )
        options = data["node"]["field"]["options"]
        self._status_option_ids = {opt["name"]: opt["id"] for opt in options}

    def get_status_option_id(self, status_name: str) -> str:
        """Get the option ID for a status name."""
        if status_name not in self._status_option_ids:
            raise ValueError(f"Unknown status: {status_name}. Known: {list(self._status_option_ids.keys())}")
        return self._status_option_ids[status_name]

    # --- Query issues by project status ---

    def fetch_issues_by_status(self, status_name: str) -> list[dict]:
        """Fetch all open issues in the project with the given status.

        Returns a list of dicts with keys: number, title, body, repo, project_item_id
        """
        status_option_id = self.get_status_option_id(status_name)
        issues = []
        cursor = None

        while True:
            after_clause = f', after: "{cursor}"' if cursor else ""
            data = self._graphql(
                f"""
                query($projectId: ID!) {{
                    node(id: $projectId) {{
                        ... on ProjectV2 {{
                            items(first: 50{after_clause}) {{
                                pageInfo {{
                                    hasNextPage
                                    endCursor
                                }}
                                nodes {{
                                    id
                                    fieldValueByName(name: "Status") {{
                                        ... on ProjectV2ItemFieldSingleSelectValue {{
                                            optionId
                                        }}
                                    }}
                                    content {{
                                        ... on Issue {{
                                            number
                                            title
                                            body
                                            state
                                            repository {{
                                                nameWithOwner
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
                """,
                {"projectId": self._project_id},
            )

            items = data["node"]["items"]
            for node in items["nodes"]:
                field_value = node.get("fieldValueByName")
                if not field_value:
                    continue
                if field_value.get("optionId") != status_option_id:
                    continue
                content = node.get("content")
                if not content or not content.get("number"):
                    continue
                if content.get("state") != "OPEN":
                    continue
                issues.append({
                    "number": content["number"],
                    "title": content["title"],
                    "body": content.get("body", ""),
                    "repo": content["repository"]["nameWithOwner"],
                    "project_item_id": node["id"],
                })

            if items["pageInfo"]["hasNextPage"]:
                cursor = items["pageInfo"]["endCursor"]
            else:
                break

        return issues

    # --- Update project status ---

    def update_status(self, project_item_id: str, new_status_name: str):
        """Update an issue's status in the project."""
        option_id = self.get_status_option_id(new_status_name)
        self._graphql(
            """
            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
                updateProjectV2ItemFieldValue(input: {
                    projectId: $projectId
                    itemId: $itemId
                    fieldId: $fieldId
                    value: { singleSelectOptionId: $optionId }
                }) {
                    projectV2Item { id }
                }
            }
            """,
            {
                "projectId": self._project_id,
                "itemId": project_item_id,
                "fieldId": self._status_field_id,
                "optionId": option_id,
            },
        )

    # --- Issue comments (REST API — simpler) ---

    def add_comment(self, repo_name: str, issue_number: int, body: str):
        """Post a comment on an issue."""
        owner, repo = repo_name.split("/")
        self._rest_post(f"/repos/{owner}/{repo}/issues/{issue_number}/comments", {"body": body})

    def close_issue(self, repo_name: str, issue_number: int):
        """Close an issue."""
        owner, repo = repo_name.split("/")
        requests.patch(
            f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}",
            json={"state": "closed", "state_reason": "completed"},
            headers=self.headers,
            timeout=30,
        )

    def get_attempt_count(self, repo_name: str, issue_number: int) -> int:
        """Count orchestrator attempt comments on an issue."""
        owner, repo = repo_name.split("/")
        comments = self._rest_get(f"/repos/{owner}/{repo}/issues/{issue_number}/comments")
        return sum(
            1
            for c in comments
            if c["body"].startswith(ORCHESTRATOR_TAG) and "Attempt" in c["body"] and "completed" in c["body"]
        )

    # --- PR operations (REST API) ---

    def merge_pr(self, repo_name: str, pr_number: int, merge_method: str = "squash") -> bool:
        """Merge a pull request. Returns True on success, False on failure."""
        owner, repo = repo_name.split("/")
        try:
            resp = requests.put(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/merge",
                json={"merge_method": merge_method},
                headers=self.headers,
                timeout=30,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def find_pr_for_branch(self, repo_name: str, branch: str) -> int | None:
        """Find the PR number for a given branch. Returns None if not found."""
        owner, repo = repo_name.split("/")
        pulls = self._rest_get(f"/repos/{owner}/{repo}/pulls?state=open&head={owner}:{branch}")
        if pulls:
            return pulls[0]["number"]
        return None
