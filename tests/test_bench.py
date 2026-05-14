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


def test_aggregate_by_issue_single_issue_multi_attempts():
    """Two coding attempts on same issue → attempts=2, sums correct."""
    from bench import aggregate_by_issue
    rows = [
        {"issue_number": 5, "agent_role": "coding", "model": "m1",
         "cost_usd": 1.0, "outcome": "error_max_budget_usd",
         "timestamp": "20260514T010000", "turns": 30,
         "cache_read_tokens": 0, "output_tokens": 0},
        {"issue_number": 5, "agent_role": "coding", "model": "m1",
         "cost_usd": 0.8, "outcome": "success",
         "timestamp": "20260514T020000", "turns": 10,
         "cache_read_tokens": 0, "output_tokens": 0},
        {"issue_number": 5, "agent_role": "testing", "model": "m2",
         "cost_usd": 0.05, "outcome": "success",
         "timestamp": "20260514T021000", "turns": 1,
         "cache_read_tokens": 0, "output_tokens": 0},
        {"issue_number": 5, "agent_role": "review", "model": "m3",
         "cost_usd": 0.3, "outcome": "success",
         "timestamp": "20260514T022000", "turns": 1,
         "cache_read_tokens": 0, "output_tokens": 0},
    ]
    out = aggregate_by_issue(rows)
    assert len(out) == 1
    r = out[0]
    assert r["issue_number"] == 5
    assert r["attempts"] == 2
    assert r["budget_caps"] == 1
    assert r["models_used"] == {"coding": "m1", "testing": "m2", "review": "m3"}
    assert r["total_cost_usd"] == pytest.approx(2.15)
    assert r["final_outcome"] == "success"  # latest coding-role timestamp


def test_aggregate_by_issue_models_used_none_when_no_log_for_role():
    from bench import aggregate_by_issue
    rows = [
        {"issue_number": 5, "agent_role": "coding", "model": "m1",
         "cost_usd": 1.0, "outcome": "success",
         "timestamp": "20260514T010000", "turns": 1,
         "cache_read_tokens": 0, "output_tokens": 0},
    ]
    out = aggregate_by_issue(rows)
    assert out[0]["models_used"] == {"coding": "m1", "testing": None, "review": None}


def test_aggregate_by_issue_assigns_attempt_index_within_role():
    """Multiple coding logs on the same issue → attempt_index 1,2,... by timestamp."""
    from bench import aggregate_by_issue
    rows = [
        {"issue_number": 5, "agent_role": "coding", "model": "m1",
         "cost_usd": 1.0, "outcome": "error_max_budget_usd",
         "timestamp": "20260514T020000", "turns": 30,
         "cache_read_tokens": 0, "output_tokens": 0},
        {"issue_number": 5, "agent_role": "coding", "model": "m1",
         "cost_usd": 0.8, "outcome": "success",
         "timestamp": "20260514T010000", "turns": 10,
         "cache_read_tokens": 0, "output_tokens": 0},
    ]
    aggregate_by_issue(rows)
    # After aggregation the input rows should be tagged with attempt_index by timestamp.
    timestamps_in_order = sorted([(r["timestamp"], r["attempt_index"]) for r in rows])
    # Earliest timestamp = attempt 1, next = attempt 2
    assert timestamps_in_order[0][1] == 1
    assert timestamps_in_order[1][1] == 2


def test_aggregate_by_issue_multiple_issues_sorted():
    from bench import aggregate_by_issue
    rows = [
        {"issue_number": 7, "agent_role": "coding", "model": "m",
         "cost_usd": 0.5, "outcome": "success",
         "timestamp": "t1", "turns": 1, "cache_read_tokens": 0, "output_tokens": 0},
        {"issue_number": 3, "agent_role": "coding", "model": "m",
         "cost_usd": 0.5, "outcome": "success",
         "timestamp": "t1", "turns": 1, "cache_read_tokens": 0, "output_tokens": 0},
    ]
    out = aggregate_by_issue(rows)
    assert [r["issue_number"] for r in out] == [3, 7]


def test_aggregate_by_version_basic():
    from bench import aggregate_by_version
    issue_rows = [
        {"issue_number": 1, "attempts": 1, "budget_caps": 0,
         "models_used": {}, "total_cost_usd": 1.0, "final_outcome": "success"},
        {"issue_number": 2, "attempts": 2, "budget_caps": 1,
         "models_used": {}, "total_cost_usd": 6.0, "final_outcome": "success"},
        {"issue_number": 3, "attempts": 1, "budget_caps": 0,
         "models_used": {}, "total_cost_usd": 2.0, "final_outcome": "success"},
    ]
    version_map = {1: (0, 14), 2: (0, 14), 3: (0, 15)}
    out = aggregate_by_version(issue_rows, version_map)
    by_v = {r["version"]: r for r in out}
    v14 = by_v["v0.14"]
    assert v14["issues"] == 2
    assert v14["attempts"] == 3
    assert v14["budget_caps"] == 1
    assert v14["first_pass_rate"] == pytest.approx(0.5)  # 1 of 2 was attempts==1+success
    assert v14["total_cost_usd"] == pytest.approx(7.0)
    assert v14["mean_cost_per_issue"] == pytest.approx(3.5)
    v15 = by_v["v0.15"]
    assert v15["first_pass_rate"] == 1.0


def test_aggregate_by_version_bootstrap_label():
    from bench import aggregate_by_version
    issue_rows = [
        {"issue_number": 1, "attempts": 1, "budget_caps": 0,
         "models_used": {}, "total_cost_usd": 1.0, "final_outcome": "success"},
    ]
    version_map = {1: (0, 0)}
    out = aggregate_by_version(issue_rows, version_map)
    assert out[0]["version"] == "bootstrap"


def test_aggregate_by_version_unversioned_bucket():
    from bench import aggregate_by_version
    issue_rows = [
        {"issue_number": 1, "attempts": 1, "budget_caps": 0,
         "models_used": {}, "total_cost_usd": 1.0, "final_outcome": "success"},
        {"issue_number": 2, "attempts": 1, "budget_caps": 0,
         "models_used": {}, "total_cost_usd": 2.0, "final_outcome": "success"},
    ]
    version_map = {1: (0, 14)}  # issue 2 missing → goes to (no version) bucket
    out = aggregate_by_version(issue_rows, version_map)
    by_v = {r["version"]: r for r in out}
    assert "(no version)" in by_v
    assert by_v["(no version)"]["issues"] == 1


def test_aggregate_by_version_first_pass_rate_excludes_in_flight():
    """An issue with attempts=1 but final_outcome != 'success' is excluded from denominator."""
    from bench import aggregate_by_version
    issue_rows = [
        {"issue_number": 1, "attempts": 1, "budget_caps": 0,
         "models_used": {}, "total_cost_usd": 1.0, "final_outcome": "success"},
        {"issue_number": 2, "attempts": 1, "budget_caps": 0,
         "models_used": {}, "total_cost_usd": 1.0, "final_outcome": "(no-coding-log)"},
    ]
    version_map = {1: (0, 14), 2: (0, 14)}
    out = aggregate_by_version(issue_rows, version_map)
    # Only issue 1 has a resolvable final_outcome → denominator = 1, numerator = 1
    assert out[0]["first_pass_rate"] == 1.0


def test_aggregate_by_version_sorted():
    from bench import aggregate_by_version
    issue_rows = [
        {"issue_number": 1, "attempts": 1, "budget_caps": 0,
         "models_used": {}, "total_cost_usd": 1.0, "final_outcome": "success"},
        {"issue_number": 2, "attempts": 1, "budget_caps": 0,
         "models_used": {}, "total_cost_usd": 1.0, "final_outcome": "success"},
    ]
    version_map = {1: (0, 15), 2: (0, 14)}
    out = aggregate_by_version(issue_rows, version_map)
    assert [r["version"] for r in out] == ["v0.14", "v0.15"]


from unittest.mock import patch, MagicMock


def test_fetch_version_map_returns_map_on_success():
    from bench import fetch_version_map
    config = {
        "project": {"owner": "owner", "number": 1, "status_field_id": "PVTSSF_test"},
    }
    fake_issues = [
        {"number": 261, "title": "[v0.14] Rename CoverageTracker"},
        {"number": 269, "title": "[v0.15] Surface-flush paintball splat"},
        {"number": 999, "title": "Untagged issue"},  # no version → skipped
    ]
    with patch("bench.GitHubClient") as MockGH:
        mock = MockGH.return_value
        mock.fetch_all_project_issues.return_value = fake_issues
        m = fetch_version_map(config)
    assert m == {261: (0, 14), 269: (0, 15)}


def test_fetch_version_map_returns_none_on_exception(capsys):
    """A GitHub failure prints a warning to stderr and returns None."""
    from bench import fetch_version_map
    config = {
        "project": {"owner": "owner", "number": 1, "status_field_id": "PVTSSF_test"},
    }
    with patch("bench.GitHubClient") as MockGH:
        MockGH.return_value.fetch_all_project_issues.side_effect = RuntimeError("offline")
        m = fetch_version_map(config)
    assert m is None
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()
    assert "offline" in captured.err.lower()


def test_fetch_version_map_returns_none_when_config_lacks_project():
    """If playbook.yaml has no `project` block, can't query GitHub."""
    from bench import fetch_version_map
    m = fetch_version_map({})
    assert m is None


def test_render_stdout_contains_both_section_headers():
    from bench import render_stdout
    by_version = [{
        "version": "v0.14", "issues": 2, "attempts": 3, "first_pass_rate": 0.5,
        "budget_caps": 1, "total_cost_usd": 7.0, "mean_cost_per_issue": 3.5,
    }]
    by_issue = [{
        "issue_number": 1, "attempts": 1, "budget_caps": 0,
        "models_used": {"coding": "claude-sonnet-4-6", "testing": "claude-haiku-4-5",
                        "review": "claude-opus-4-7"},
        "total_cost_usd": 1.0, "final_outcome": "success",
    }]
    out = render_stdout(by_version, by_issue)
    assert "=== By version ===" in out
    assert "=== By issue ===" in out
    assert "v0.14" in out
    assert "claude-sonnet-4-6" in out


def test_render_stdout_no_version_table_when_empty():
    from bench import render_stdout
    by_issue = [{
        "issue_number": 1, "attempts": 1, "budget_caps": 0,
        "models_used": {"coding": "m", "testing": None, "review": None},
        "total_cost_usd": 1.0, "final_outcome": "success",
    }]
    out = render_stdout([], by_issue)
    assert "=== By version ===" not in out
    assert "=== By issue ===" in out
