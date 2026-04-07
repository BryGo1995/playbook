import re

VERSION_PATTERN = re.compile(r"\[v(\d+)\.(\d+)\]")
BOOTSTRAP_PATTERN = re.compile(r"\[bootstrap\]", re.IGNORECASE)


def parse_version(title: str) -> tuple[int, int] | None:
    """Extract version tuple from issue title. Returns (major, minor) or None."""
    bootstrap_match = BOOTSTRAP_PATTERN.search(title)
    if bootstrap_match:
        return (0, 0)
    version_match = VERSION_PATTERN.search(title)
    if version_match:
        return (int(version_match.group(1)), int(version_match.group(2)))
    return None


def get_active_version(issues: list[dict]) -> tuple[int, int] | None:
    """Determine the lowest incomplete version from a list of issues.

    Each issue dict must have 'title' and 'status' keys.
    Returns the version tuple of the lowest version that has any issue
    not in 'Done' status, or None if all versioned issues are done.
    """
    version_statuses: dict[tuple[int, int], list[str]] = {}
    for issue in issues:
        version = parse_version(issue["title"])
        if version is None:
            continue
        version_statuses.setdefault(version, []).append(issue["status"])

    if not version_statuses:
        return None

    for version in sorted(version_statuses.keys()):
        statuses = version_statuses[version]
        if not all(s == "Done" for s in statuses):
            return version

    return None
