"""Post-hoc cost+quality benchmark over .playbook/logs/*.json.

Reads each agent NDJSON log, extracts a row dict (cost, turns, outcome,
model, role, tokens), aggregates per-issue and per-version, and renders
tables to stdout/JSON/Markdown.
"""
import json
import os
import re

# Filename schemas:
#  - new:    <safe_repo>-<issue>-<role>-<YYYYMMDDTHHMMSS>.json
#  - legacy: <safe_repo>-<issue>-<YYYYMMDDTHHMMSS>.json
_FILENAME_NEW = re.compile(r"^(.+)-(\d+)-(coding|testing|review)-(\d{8}T\d{6})\.json$")
_FILENAME_LEGACY = re.compile(r"^(.+)-(\d+)-(\d{8}T\d{6})\.json$")


def _parse_filename(path: str) -> dict | None:
    """Return {issue_number, role_from_filename, timestamp} or None if unrecognized."""
    name = os.path.basename(path)
    m = _FILENAME_NEW.match(name)
    if m:
        return {
            "issue_number": int(m.group(2)),
            "role_from_filename": m.group(3),
            "timestamp": m.group(4),
        }
    m = _FILENAME_LEGACY.match(name)
    if m:
        return {
            "issue_number": int(m.group(2)),
            "role_from_filename": None,
            "timestamp": m.group(3),
        }
    return None


def extract_log_row(log_path: str) -> dict | None:
    """Parse one agent NDJSON log into a row dict.

    Returns None if the file is unreadable, the filename is unrecognized, or
    no terminal `result` record is present. Skips malformed JSON lines.
    """
    fname_info = _parse_filename(log_path)
    if fname_info is None:
        return None

    model = "(unknown)"
    outcome = "(unknown)"
    turns = 0
    cost_usd = 0.0
    cache_read_tokens = 0
    output_tokens = 0
    tools_used: set[str] = set()
    seen_result = False

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue  # tolerate corrupt lines
                if not isinstance(rec, dict):
                    continue

                # init record carries the model
                if rec.get("type") == "system" and rec.get("subtype") == "init":
                    if isinstance(rec.get("model"), str):
                        model = rec["model"]

                # assistant turn usage + tool_use names
                msg = rec.get("message") if isinstance(rec.get("message"), dict) else None
                if msg:
                    usage = msg.get("usage")
                    if isinstance(usage, dict):
                        try:
                            cache_read_tokens += int(usage.get("cache_read_input_tokens", 0) or 0)
                            output_tokens += int(usage.get("output_tokens", 0) or 0)
                        except (ValueError, TypeError):
                            pass  # tolerate non-numeric token values in malformed records
                    for blk in msg.get("content", []) or []:
                        if isinstance(blk, dict) and blk.get("type") == "tool_use":
                            name = blk.get("name", "")
                            if isinstance(name, str) and name:
                                tools_used.add(name)

                # terminal result
                if rec.get("type") == "result":
                    seen_result = True
                    outcome = rec.get("subtype") or "(unknown)"
                    try:
                        turns = int(rec.get("num_turns") or 0)
                    except (ValueError, TypeError):
                        turns = 0
                    try:
                        cost_usd = float(rec.get("total_cost_usd") or 0.0)
                    except (ValueError, TypeError):
                        cost_usd = 0.0
    except OSError:
        return None

    if not seen_result:
        return None

    return {
        "log_path": log_path,
        "filename": os.path.basename(log_path),
        "issue_number": fname_info["issue_number"],
        "agent_role": fname_info["role_from_filename"] or "unknown",  # heuristic patched in Task 3
        "model": model,
        "cost_usd": cost_usd,
        "turns": turns,
        "cache_read_tokens": cache_read_tokens,
        "output_tokens": output_tokens,
        "outcome": outcome,
        "timestamp": fname_info["timestamp"],
        "attempt_index": 0,  # filled in during aggregation
        "_tools_used": tools_used,  # internal — consumed by infer_role
    }
