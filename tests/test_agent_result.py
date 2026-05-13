"""Tests for agent_result.detect_budget_cap_in_log.

Covers the happy path (real result record), a no-cap log, malformed lines (must
not crash), and missing/None paths (must return False).
"""
import os

from agent_result import detect_budget_cap_in_log


def _write_lines(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + ("\n" if lines else ""))
    return str(p)


def test_detects_budget_cap_result_record(tmp_path):
    """A canonical Anthropic-CLI terminal record means budget was exhausted."""
    log = _write_lines(tmp_path, "log.json", [
        '{"type":"system","subtype":"init"}',
        '{"type":"assistant","message":{"usage":{"output_tokens":120}}}',
        '{"type":"result","subtype":"error_max_budget_usd","total_cost_usd":5.04,'
        '"errors":["Reached maximum budget ($5)"]}',
    ])
    assert detect_budget_cap_in_log(log) is True


def test_returns_false_when_log_has_no_budget_record(tmp_path):
    """A log with a clean end_turn result should not flag as budget-cap."""
    log = _write_lines(tmp_path, "log.json", [
        '{"type":"system","subtype":"init"}',
        '{"type":"assistant","message":{"stop_reason":"end_turn"}}',
        '{"type":"result","subtype":"success","total_cost_usd":2.10}',
    ])
    assert detect_budget_cap_in_log(log) is False


def test_returns_false_when_substring_appears_only_in_value_not_result(tmp_path):
    """The substring 'error_max_budget_usd' must be in the actual result.subtype,
    not just mentioned in some assistant message string. The cheap prefilter does
    the substring match, but the JSON parse + structural check is what counts."""
    log = _write_lines(tmp_path, "log.json", [
        '{"type":"assistant","message":{"content":[{"type":"text",'
        '"text":"the agent worried about error_max_budget_usd"}]}}',
        '{"type":"result","subtype":"end_turn"}',
    ])
    assert detect_budget_cap_in_log(log) is False


def test_tolerates_malformed_lines(tmp_path):
    """A JSON parse error on one line must not blow up the whole detection."""
    log = _write_lines(tmp_path, "log.json", [
        '{"type":"system","subtype":"init"}',
        'this is not valid json error_max_budget_usd',
        '',
        '{"type":"result","subtype":"error_max_budget_usd"}',
    ])
    assert detect_budget_cap_in_log(log) is True


def test_returns_false_for_none_path():
    """No log path means no evidence — used when agent state predates log_path tracking."""
    assert detect_budget_cap_in_log(None) is False


def test_returns_false_for_missing_file(tmp_path):
    """A path that doesn't exist returns False rather than raising."""
    missing = os.path.join(str(tmp_path), "does-not-exist.json")
    assert detect_budget_cap_in_log(missing) is False


def test_returns_false_for_empty_file(tmp_path):
    """An empty log (agent died before writing anything) is not a budget-cap."""
    log = _write_lines(tmp_path, "empty.json", [])
    assert detect_budget_cap_in_log(log) is False
