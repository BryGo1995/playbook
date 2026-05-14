import json
import os
import shutil
import pytest

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "bench_logs")


@pytest.fixture
def logs_dir(tmp_path):
    """Yield a fresh logs dir with no fixture files copied; tests copy what they need."""
    d = tmp_path / ".playbook" / "logs"
    d.mkdir(parents=True)
    return d


def _copy_fixture(src_name: str, dest_path) -> str:
    """Copy a fixture into dest_path and return the resulting absolute path."""
    shutil.copy(os.path.join(FIXTURE_DIR, src_name), dest_path)
    return str(dest_path)


def test_extract_log_row_coding_success(logs_dir):
    from bench import extract_log_row
    dest = logs_dir / "owner-repo-42-coding-20260514T024012.json"
    path = _copy_fixture("coding_success.json", dest)
    row = extract_log_row(path)
    assert row is not None
    assert row["issue_number"] == 42
    assert row["agent_role"] == "coding"
    assert row["model"] == "claude-sonnet-4-6"
    assert row["cost_usd"] == 1.23
    assert row["turns"] == 1
    assert row["outcome"] == "success"
    assert row["cache_read_tokens"] == 1000
    assert row["output_tokens"] == 20
    assert row["timestamp"] == "20260514T024012"


def test_extract_log_row_budget_cap(logs_dir):
    from bench import extract_log_row
    dest = logs_dir / "owner-repo-42-coding-20260514T030000.json"
    path = _copy_fixture("coding_budget_cap.json", dest)
    row = extract_log_row(path)
    assert row["outcome"] == "error_max_budget_usd"
    assert row["cost_usd"] == 5.05
    assert row["turns"] == 50


def test_extract_log_row_corrupt_lines_skipped(logs_dir):
    from bench import extract_log_row
    dest = logs_dir / "owner-repo-99-coding-20260514T040000.json"
    path = _copy_fixture("corrupt.json", dest)
    row = extract_log_row(path)
    # Bad JSON line is skipped; init + result still parse → row is returned
    assert row is not None
    assert row["outcome"] == "success"
    assert row["cost_usd"] == 0.10


def test_extract_log_row_missing_result_returns_none(logs_dir):
    """A log file with no terminal 'result' record can't be aggregated cleanly."""
    from bench import extract_log_row
    dest = logs_dir / "owner-repo-1-coding-20260514T050000.json"
    dest.write_text('{"type":"system","subtype":"init","model":"claude-opus-4-7"}\n')
    row = extract_log_row(str(dest))
    assert row is None


def test_extract_log_row_unreadable_file_returns_none(tmp_path):
    """A path that doesn't exist returns None rather than raising."""
    from bench import extract_log_row
    assert extract_log_row(str(tmp_path / "does-not-exist.json")) is None


def test_extract_log_row_non_numeric_tokens_tolerated(tmp_path):
    """Valid JSON with string values where numbers are expected -> tolerated, not crash."""
    from bench import extract_log_row
    p = tmp_path / "owner-repo-7-coding-20260514T060000.json"
    p.write_text(
        '{"type":"system","subtype":"init","model":"claude-sonnet-4-6"}\n'
        # Usage with string tokens
        '{"type":"assistant","message":{"model":"x","content":[],"usage":{"cache_read_input_tokens":"NaN","output_tokens":"oops"}}}\n'
        # Result with string numerics
        '{"type":"result","subtype":"success","num_turns":"bad","total_cost_usd":"also bad"}\n'
    )
    row = extract_log_row(str(p))
    assert row is not None
    assert row["outcome"] == "success"
    # Bad values should have been swallowed and left at 0
    assert row["cache_read_tokens"] == 0
    assert row["output_tokens"] == 0
    assert row["turns"] == 0
    assert row["cost_usd"] == 0.0


def test_infer_role_from_new_filename(logs_dir):
    from bench import extract_log_row
    dest = logs_dir / "owner-repo-7-testing-20260514T060000.json"
    _copy_fixture("testing_success.json", dest)
    row = extract_log_row(str(dest))
    # Even though the heuristic would say "testing" anyway, filename wins.
    assert row["agent_role"] == "testing"


def test_infer_role_heuristic_coding_from_legacy_filename(logs_dir):
    """Legacy filename with Edit/Write usage → coding."""
    from bench import extract_log_row
    dest = logs_dir / "owner-repo-7-20260514T060000.json"
    _copy_fixture("legacy_coding.json", dest)
    row = extract_log_row(str(dest))
    assert row["agent_role"] == "coding"


def test_infer_role_heuristic_testing_from_legacy_filename(tmp_path):
    """Legacy filename with only Read/Bash usage → testing."""
    from bench import extract_log_row
    p = tmp_path / "owner-repo-7-20260514T060000.json"
    p.write_text(
        '{"type":"system","subtype":"init","model":"claude-haiku-4-5"}\n'
        '{"type":"assistant","message":{"model":"x","content":[{"type":"tool_use","name":"Read","id":"t1","input":{}}],"usage":{}}}\n'
        '{"type":"assistant","message":{"model":"x","content":[{"type":"tool_use","name":"Bash","id":"t2","input":{}}],"usage":{}}}\n'
        '{"type":"result","subtype":"success","num_turns":2,"total_cost_usd":0.1}\n'
    )
    row = extract_log_row(str(p))
    assert row["agent_role"] == "testing"


def test_infer_role_heuristic_review_from_legacy_filename(tmp_path):
    """Legacy filename with github MCP tool usage → review."""
    from bench import extract_log_row
    p = tmp_path / "owner-repo-7-20260514T060000.json"
    p.write_text(
        '{"type":"system","subtype":"init","model":"claude-opus-4-7"}\n'
        '{"type":"assistant","message":{"model":"x","content":[{"type":"tool_use","name":"mcp__github__pull_request_read","id":"t1","input":{}}],"usage":{}}}\n'
        '{"type":"result","subtype":"success","num_turns":1,"total_cost_usd":0.3}\n'
    )
    row = extract_log_row(str(p))
    assert row["agent_role"] == "review"


def test_infer_role_unknown_when_no_signal(tmp_path):
    """Legacy filename with no tool usage signal → unknown."""
    from bench import extract_log_row
    p = tmp_path / "owner-repo-7-20260514T060000.json"
    p.write_text(
        '{"type":"system","subtype":"init","model":"claude-sonnet-4-6"}\n'
        '{"type":"result","subtype":"success","num_turns":1,"total_cost_usd":0.05}\n'
    )
    row = extract_log_row(str(p))
    assert row["agent_role"] == "unknown"
