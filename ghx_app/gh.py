import json
import subprocess
from typing import Any

PR_LIST_FIELDS = "number,title,headRefName,author,isDraft,state,reviewDecision,additions,deletions"
ISSUE_LIST_FIELDS = "number,title,author,state,labels,assignees,updatedAt,url"

CONTEXT_QUERY = """
query($owner: String!, $name: String!, $pr: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) {
      number title state isDraft url
      labels(first: 20) { nodes { name color } }
      closingIssuesReferences(first: 30) {
        nodes {
          number title state url
          labels(first: 20) { nodes { name color } }
        }
      }
    }
  }
}
"""

WORK_QUERY = """
query($owner: String!, $name: String!) {
  viewer { login }
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 50, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        number title headRefName isDraft reviewDecision additions deletions url
        author { login }
        closingIssuesReferences(first: 10) { nodes { number } }
      }
    }
    issues(states: OPEN, first: 50, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        number title url updatedAt
        author { login }
        labels(first: 20) { nodes { name color } }
        assignees(first: 10) { nodes { login } }
      }
    }
  }
}
"""

GHOST = {"login": "ghost"}


def run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def gh_json(args: list[str]) -> Any:
    result = run_gh(args)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh failed")
    return json.loads(result.stdout)


def graphql(query: str, **variables: str | int) -> dict[str, Any]:
    cmd = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        flag = "-F" if isinstance(value, int) else "-f"
        cmd.extend([flag, f"{key}={value}"])
    return gh_json(cmd).get("data") or {}


def pr_list_args(mine: bool, search: str = "") -> list[str]:
    args = ["pr", "list", "--json", PR_LIST_FIELDS, "--limit", "50"]
    if mine:
        args.extend(["--author", "@me"])
    if search:
        args.extend(["--search", search])
    return args


def issue_list_args(mine: bool, search: str = "") -> list[str]:
    args = ["issue", "list", "--json", ISSUE_LIST_FIELDS, "--limit", "50"]
    if mine:
        args.extend(["--assignee", "@me"])
    if search:
        args.extend(["--search", search])
    return args


def detect_repo() -> str | None:
    result = run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    return result.stdout.strip() or None if result.returncode == 0 else None


def current_branch() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() or "(detached)"


def get_pr_number() -> int | None:
    result = run_gh(["pr", "view", "--json", "number", "-q", ".number"])
    number = result.stdout.strip()
    return int(number) if result.returncode == 0 and number else None


def normalize_state(state: str, is_draft: bool) -> str:
    state = state.lower()
    return "draft" if state == "open" and is_draft else state


def labels_of(node: dict) -> list[dict]:
    return [{"name": l["name"], "color": l["color"]} for l in node["labels"]["nodes"]]


def fetch_context(repo: str, pr: int) -> dict | None:
    owner, _, name = repo.partition("/")
    try:
        data = graphql(CONTEXT_QUERY, owner=owner, name=name, pr=pr)
    except (RuntimeError, json.JSONDecodeError):
        return None
    node = (data.get("repository") or {}).get("pullRequest")
    if not node:
        return None
    return {
        "pr": {
            "kind": "pr",
            "number": node["number"],
            "title": node["title"],
            "state": normalize_state(node["state"], node["isDraft"]),
            "url": node["url"],
            "labels": labels_of(node),
        },
        "issues": [
            {
                "kind": "issue",
                "number": issue["number"],
                "title": issue["title"],
                "state": normalize_state(issue["state"], False),
                "url": issue["url"],
                "labels": labels_of(issue),
            }
            for issue in node["closingIssuesReferences"]["nodes"]
        ],
    }


def fetch_work(repo: str) -> tuple[str, list[dict], list[dict]]:
    owner, _, name = repo.partition("/")
    data = graphql(WORK_QUERY, owner=owner, name=name)
    repository = data["repository"]
    prs = [
        {
            "kind": "pr",
            "number": node["number"],
            "title": node["title"],
            "headRefName": node["headRefName"],
            "author": node["author"] or GHOST,
            "isDraft": node["isDraft"],
            "reviewDecision": node["reviewDecision"],
            "additions": node["additions"],
            "deletions": node["deletions"],
            "url": node["url"],
            "closes": [issue["number"] for issue in node["closingIssuesReferences"]["nodes"]],
        }
        for node in repository["pullRequests"]["nodes"]
    ]
    issues = [
        {
            "kind": "issue",
            "number": node["number"],
            "title": node["title"],
            "author": node["author"] or GHOST,
            "labels": labels_of(node),
            "assignees": node["assignees"]["nodes"],
            "url": node["url"],
            "updatedAt": node["updatedAt"],
        }
        for node in repository["issues"]["nodes"]
    ]
    return data["viewer"]["login"], prs, issues


def open_url(url: str) -> None:
    subprocess.Popen(
        ["xdg-open", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )


def open_pr_in_browser(number: int) -> None:
    subprocess.Popen(
        ["gh", "pr", "view", str(number), "--web"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
