# agent_result.py
"""Post-mortem inspection of a coding agent's NDJSON log.

The agent writes one JSON object per line. When the agent exhausts the per-attempt
USD budget cap, the harness writes a terminal record:

    {"type": "result", "subtype": "error_max_budget_usd", ...}

We use that signal to distinguish budget-cap failures from "agent gave up without
committing" — the orchestrator branches its retry policy on the difference.

Reading is best-effort: a missing/unreadable/malformed log is treated as "no
budget-cap evidence" rather than raising, so a log-read bug can never block the
retry flow.
"""
import json
import os


def detect_budget_cap_in_log(log_path: str | None) -> bool:
    """True if the log contains a result record with subtype error_max_budget_usd.

    Returns False for any kind of read failure — missing file, unreadable bytes,
    malformed JSON line — so callers can use this as a pure signal without try/except.
    """
    if not log_path or not os.path.isfile(log_path):
        return False
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Cheap pre-filter — the field appears in both keys and values,
                # but every match is worth a real JSON parse anyway.
                if "error_max_budget_usd" not in line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if (
                    isinstance(rec, dict)
                    and rec.get("type") == "result"
                    and rec.get("subtype") == "error_max_budget_usd"
                ):
                    return True
    except OSError:
        return False
    return False
