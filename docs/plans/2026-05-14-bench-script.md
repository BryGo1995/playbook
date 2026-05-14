# Cost/Quality Bench Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `python3 -m bench` invocation that reads `.playbook/logs/*.json` from a project repo and prints per-issue + per-version cost-and-quality tables, with GitHub-issue-title → version mapping when reachable.

**Architecture:** A single new top-level module `bench.py` exposes small, pure-ish functions: log → row extraction, role inference, per-issue aggregation, per-version aggregation, three output renderers (stdout/json/markdown), and a `main()` that wires CLI args together. Reads `playbook.yaml` from cwd, reuses `GitHubClient.fetch_all_project_issues` and `versioning.parse_version` for version grouping, and degrades to issue-only output when GitHub is unreachable. A small upstream change in `state.py` adds an `agent_type` segment to new log filenames so future bench runs don't need the legacy role-inference heuristic.

**Tech Stack:** Python 3 stdlib only (no new deps), `argparse`, `json`, pytest with `unittest.mock`. Existing modules reused: `github_client.GitHubClient`, `versioning.parse_version`, `config.load_config`.

**Spec:** `docs/specs/2026-05-14-model-tiering-and-bench-design.md`

---

## File Structure

**New files:**
- `bench.py` (project root) — single module containing extraction, aggregation, rendering, and CLI entry. All functions are module-level (pure where possible). Mirrors the `summary.py` shape.
- `tests/test_bench.py` — unit tests for each function plus end-to-end CLI smoke tests.
- `tests/fixtures/bench_logs/` — directory of crafted NDJSON files used by extraction and aggregation tests. Six files: `coding_success.json`, `coding_budget_cap.json`, `testing_success.json`, `review_success.json`, `legacy_coding.json`, `corrupt.json`.

**Modified files:**
- `state.py` — `log_path` gains a required `agent_type: str` parameter; filename schema bumps from `<repo>-<issue>-<ts>.json` to `<repo>-<issue>-<role>-<ts>.json`.
- `orchestrator.py` — three dispatch sites pass their role string to `state.log_path`.

**Modified tests:**
- `tests/test_state.py` — assert the new filename schema includes the role segment.

---

## Data shapes (referenced throughout)

For consistency across tasks, the canonical shapes:

**Log row** (one per `.json` log file):
```python
{
    "log_path": str,              # absolute path
    "filename": str,              # basename
    "issue_number": int,
    "agent_role": str,            # "coding" | "testing" | "review" | "unknown"
    "model": str,                 # e.g. "claude-sonnet-4-6", or "(unknown)"
    "cost_usd": float,
    "turns": int,
    "cache_read_tokens": int,
    "output_tokens": int,
    "outcome": str,               # e.g. "success" | "error_max_budget_usd" | "(unknown)"
    "timestamp": str,             # raw filename segment, e.g. "20260514T024012"
    "attempt_index": int,         # 1-based, filled in during aggregation
}
```

**Per-issue aggregate row**:
```python
{
    "issue_number": int,
    "attempts": int,                              # count of coding-role logs
    "budget_caps": int,                           # count of coding logs with outcome error_max_budget_usd
    "models_used": dict[str, str | None],         # {"coding": "...", "testing": "...", "review": "..."}
    "total_cost_usd": float,                      # sum across all logs for the issue
    "final_outcome": str,                         # outcome of latest-timestamp coding log
}
```

**Per-version aggregate row**:
```python
{
    "version": str,                  # "v0.14" or "bootstrap" or "(no version)"
    "issues": int,
    "attempts": int,                 # sum of per-issue attempts
    "first_pass_rate": float,        # 0.0..1.0
    "budget_caps": int,
    "total_cost_usd": float,
    "mean_cost_per_issue": float,
}
```

---

## Task 1: Bump `state.log_path` filename schema to include agent type

**Files:**
- Modify: `state.py:67-70`
- Modify: `orchestrator.py:677, 707, 735` (three dispatch sites)
- Test: `tests/test_state.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_state.py`:

```python
def test_log_path_includes_agent_type(state_dir):
    sm = StateManager(state_dir)
    p_coding = sm.log_path("owner/repo", 42, "coding")
    p_testing = sm.log_path("owner/repo", 42, "testing")
    p_review = sm.log_path("owner/repo", 42, "review")
    assert "owner-repo-42-coding-" in os.path.basename(p_coding)
    assert "owner-repo-42-testing-" in os.path.basename(p_testing)
    assert "owner-repo-42-review-" in os.path.basename(p_review)
    # Filename pattern: <safe_repo>-<issue>-<role>-<YYYYMMDDTHHMMSS>.json
    assert p_coding.endswith(".json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state.py::test_log_path_includes_agent_type -v`
Expected: FAIL — `log_path()` signature does not accept `agent_type`.

- [ ] **Step 3: Update `state.py`**

In `state.py:67-70`, change:

```python
def log_path(self, repo: str, issue_number: int, agent_type: str) -> str:
    safe_repo = repo.replace("/", "-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return os.path.join(self.logs_dir, f"{safe_repo}-{issue_number}-{agent_type}-{timestamp}.json")
```

- [ ] **Step 4: Update `orchestrator.py` dispatch sites**

In `_dispatch_coding` (around line 677):
```python
log_path = self.state.log_path(issue["repo"], issue["number"], "coding")
```

In `_dispatch_testing` (around line 707):
```python
log_path = self.state.log_path(issue["repo"], issue["number"], "testing")
```

In `_dispatch_review` (around line 735):
```python
log_path = self.state.log_path(issue["repo"], issue["number"], "review")
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_state.py -v && pytest tests/test_orchestrator.py -v`
Expected: all pass. Orchestrator tests stay green because `log_path` is only called with positional args and now requires the third positional — every call site has been updated.

- [ ] **Step 6: Commit**

```bash
git add state.py orchestrator.py tests/test_state.py
git commit -m "feat(state): include agent_type segment in log filenames"
```

---

## Task 2: `bench.py` — log row extraction with corrupt-line tolerance

**Files:**
- Create: `bench.py`
- Create: `tests/test_bench.py`
- Create: `tests/fixtures/bench_logs/` (6 NDJSON fixtures)

- [ ] **Step 1: Create fixture files**

Create `tests/fixtures/bench_logs/coding_success.json`:

```json
{"type":"system","subtype":"init","cwd":"/x","session_id":"s1","tools":["Edit","Write","Bash","Read"],"model":"claude-sonnet-4-6"}
{"type":"assistant","message":{"model":"claude-sonnet-4-6","content":[{"type":"tool_use","name":"Edit","id":"t1","input":{}}],"usage":{"input_tokens":10,"output_tokens":20,"cache_read_input_tokens":1000,"cache_creation_input_tokens":50}}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1","content":"ok"}]}}
{"type":"result","subtype":"success","num_turns":1,"total_cost_usd":1.23,"duration_ms":1000}
```

Create `tests/fixtures/bench_logs/coding_budget_cap.json`:

```json
{"type":"system","subtype":"init","cwd":"/x","session_id":"s2","tools":["Edit","Write","Bash","Read"],"model":"claude-sonnet-4-6"}
{"type":"assistant","message":{"model":"claude-sonnet-4-6","content":[{"type":"tool_use","name":"Write","id":"t1","input":{}}],"usage":{"input_tokens":5,"output_tokens":100,"cache_read_input_tokens":5000,"cache_creation_input_tokens":200}}}
{"type":"result","subtype":"error_max_budget_usd","num_turns":50,"total_cost_usd":5.05}
```

Create `tests/fixtures/bench_logs/testing_success.json`:

```json
{"type":"system","subtype":"init","cwd":"/x","session_id":"s3","tools":["Read","Bash"],"model":"claude-haiku-4-5"}
{"type":"assistant","message":{"model":"claude-haiku-4-5","content":[{"type":"tool_use","name":"Bash","id":"t1","input":{"command":"pytest"}}],"usage":{"input_tokens":2,"output_tokens":10,"cache_read_input_tokens":500,"cache_creation_input_tokens":20}}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1","content":"PASS"}]}}
{"type":"result","subtype":"success","num_turns":1,"total_cost_usd":0.05}
```

Create `tests/fixtures/bench_logs/review_success.json`:

```json
{"type":"system","subtype":"init","cwd":"/x","session_id":"s4","tools":["Read","Bash"],"model":"claude-opus-4-7"}
{"type":"assistant","message":{"model":"claude-opus-4-7","content":[{"type":"tool_use","name":"mcp__github__pull_request_review_write","id":"t1","input":{}}],"usage":{"input_tokens":3,"output_tokens":40,"cache_read_input_tokens":2000,"cache_creation_input_tokens":100}}}
{"type":"result","subtype":"success","num_turns":1,"total_cost_usd":0.30}
```

Create `tests/fixtures/bench_logs/legacy_coding.json` (no role segment in filename — this fixture is named differently when used, see Task 3):

```json
{"type":"system","subtype":"init","cwd":"/x","session_id":"s5","tools":["Edit","Write","Bash","Read"],"model":"claude-opus-4-7"}
{"type":"assistant","message":{"model":"claude-opus-4-7","content":[{"type":"tool_use","name":"Edit","id":"t1","input":{}}],"usage":{"input_tokens":4,"output_tokens":50,"cache_read_input_tokens":3000,"cache_creation_input_tokens":150}}}
{"type":"result","subtype":"success","num_turns":2,"total_cost_usd":0.80}
```

Create `tests/fixtures/bench_logs/corrupt.json`:

```json
{"type":"system","subtype":"init","model":"claude-sonnet-4-6"}
{this is not valid json
{"type":"result","subtype":"success","num_turns":1,"total_cost_usd":0.10}
```

The intended filenames at point-of-use will follow the new schema; each test will place these fixtures into a tmp dir with the appropriate name.

- [ ] **Step 2: Write failing tests**

Create `tests/test_bench.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_bench.py -v`
Expected: `ModuleNotFoundError: No module named 'bench'`.

- [ ] **Step 4: Implement `extract_log_row`**

Create `bench.py`:

```python
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
                        cache_read_tokens += int(usage.get("cache_read_input_tokens", 0) or 0)
                        output_tokens += int(usage.get("output_tokens", 0) or 0)
                    for blk in msg.get("content", []) or []:
                        if isinstance(blk, dict) and blk.get("type") == "tool_use":
                            name = blk.get("name", "")
                            if isinstance(name, str) and name:
                                tools_used.add(name)

                # terminal result
                if rec.get("type") == "result":
                    seen_result = True
                    outcome = rec.get("subtype") or "(unknown)"
                    turns = int(rec.get("num_turns") or 0)
                    cost_usd = float(rec.get("total_cost_usd") or 0.0)
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
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_bench.py -v`
Expected: 5 passes (the 5 tests added in Step 2).

- [ ] **Step 6: Commit**

```bash
git add bench.py tests/test_bench.py tests/fixtures/bench_logs/
git commit -m "feat(bench): log-row extraction with corrupt-line tolerance"
```

---

## Task 3: `bench.py` — role inference (filename + heuristic)

**Files:**
- Modify: `bench.py`
- Modify: `tests/test_bench.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_bench.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bench.py -k "infer_role" -v`
Expected: 4 failures (the heuristic returns "unknown" today for legacy filenames; the new-filename test passes).

- [ ] **Step 3: Implement `_infer_role` + wire into `extract_log_row`**

In `bench.py`, add the helper above `extract_log_row`:

```python
def _infer_role(tools_used: set[str]) -> str:
    """Heuristic ordering for legacy-filename logs:
       1. any mcp__github__pull_request_* → review
       2. any Edit or Write → coding
       3. only Read/Bash/Grep/Glob → testing
       4. else unknown
    """
    if any(t.startswith("mcp__github__pull_request_") for t in tools_used):
        return "review"
    if "Edit" in tools_used or "Write" in tools_used:
        return "coding"
    if tools_used and tools_used.issubset({"Read", "Bash", "Grep", "Glob"}):
        return "testing"
    return "unknown"
```

Then update the last lines of `extract_log_row` so role inference fills in `agent_role` when filename didn't provide it. Replace:

```python
        "agent_role": fname_info["role_from_filename"] or "unknown",  # heuristic patched in Task 3
```

with:

```python
        "agent_role": fname_info["role_from_filename"] or _infer_role(tools_used),
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_bench.py -v`
Expected: all 10 tests pass (5 from Task 2 + 5 from this task).

- [ ] **Step 5: Commit**

```bash
git add bench.py tests/test_bench.py
git commit -m "feat(bench): infer agent role from filename or tool-usage heuristic"
```

---

## Task 4: `bench.py` — per-issue aggregation

**Files:**
- Modify: `bench.py`
- Modify: `tests/test_bench.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_bench.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bench.py -k aggregate_by_issue -v`
Expected: 4 failures — `ImportError: cannot import name 'aggregate_by_issue' from 'bench'`.

- [ ] **Step 3: Implement `aggregate_by_issue`**

Append to `bench.py`:

```python
def aggregate_by_issue(rows: list[dict]) -> list[dict]:
    """Group log rows by issue_number.

    Side effect: assigns `attempt_index` to each input row (1-based, by
    timestamp within the same agent_role). This makes per-attempt detail
    available in later renderers without a second pass.

    Returns a list sorted by issue_number ascending.
    """
    # First pass: assign attempt_index per (issue, role) sorted by timestamp
    by_issue_role: dict[tuple[int, str], list[dict]] = {}
    for r in rows:
        by_issue_role.setdefault((r["issue_number"], r["agent_role"]), []).append(r)
    for group in by_issue_role.values():
        group.sort(key=lambda r: r["timestamp"])
        for i, r in enumerate(group, start=1):
            r["attempt_index"] = i

    # Second pass: aggregate per issue
    by_issue: dict[int, list[dict]] = {}
    for r in rows:
        by_issue.setdefault(r["issue_number"], []).append(r)

    out: list[dict] = []
    for issue_number, issue_rows in sorted(by_issue.items()):
        coding_rows = [r for r in issue_rows if r["agent_role"] == "coding"]
        coding_rows.sort(key=lambda r: r["timestamp"])
        attempts = len(coding_rows)
        budget_caps = sum(1 for r in coding_rows if r["outcome"] == "error_max_budget_usd")
        models_used = {"coding": None, "testing": None, "review": None}
        for role in ("coding", "testing", "review"):
            role_rows = [r for r in issue_rows if r["agent_role"] == role]
            if role_rows:
                # Use the latest log's model (config could have changed mid-run)
                role_rows.sort(key=lambda r: r["timestamp"])
                models_used[role] = role_rows[-1]["model"]
        total_cost = sum(float(r["cost_usd"]) for r in issue_rows)
        final_outcome = coding_rows[-1]["outcome"] if coding_rows else "(no-coding-log)"

        out.append({
            "issue_number": issue_number,
            "attempts": attempts,
            "budget_caps": budget_caps,
            "models_used": models_used,
            "total_cost_usd": total_cost,
            "final_outcome": final_outcome,
        })
    return out
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_bench.py -v`
Expected: all tests pass (14 cumulative).

- [ ] **Step 5: Commit**

```bash
git add bench.py tests/test_bench.py
git commit -m "feat(bench): per-issue aggregation (attempts, budget_caps, models_used, total cost)"
```

---

## Task 5: `bench.py` — per-version aggregation

**Files:**
- Modify: `bench.py`
- Modify: `tests/test_bench.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_bench.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bench.py -k aggregate_by_version -v`
Expected: 5 failures — `aggregate_by_version` not yet exported.

- [ ] **Step 3: Implement `aggregate_by_version`**

Append to `bench.py`:

```python
def _version_label(v: tuple[int, int] | None) -> str:
    if v is None:
        return "(no version)"
    if v == (0, 0):
        return "bootstrap"
    return f"v{v[0]}.{v[1]}"


def aggregate_by_version(
    issue_rows: list[dict],
    version_map: dict[int, tuple[int, int]],
) -> list[dict]:
    """Group per-issue rows by version label.

    `version_map`: issue_number → (major, minor); issues absent from the
    map are bucketed under "(no version)".

    `first_pass_rate` excludes issues whose `final_outcome` is not a
    resolvable terminal state (e.g. "(no-coding-log)" — still in flight).
    """
    by_version: dict[tuple[int, int] | None, list[dict]] = {}
    for r in issue_rows:
        v = version_map.get(r["issue_number"])
        by_version.setdefault(v, []).append(r)

    out: list[dict] = []
    sort_key = lambda v: (v is None, v if v is not None else (0, 0))
    for v in sorted(by_version.keys(), key=sort_key):
        bucket = by_version[v]
        issues = len(bucket)
        attempts = sum(r["attempts"] for r in bucket)
        budget_caps = sum(r["budget_caps"] for r in bucket)
        total_cost = sum(float(r["total_cost_usd"]) for r in bucket)

        # first_pass_rate: denominator excludes in-flight issues
        resolved = [r for r in bucket if r["final_outcome"] not in ("(no-coding-log)",)]
        if resolved:
            first_pass = sum(
                1 for r in resolved
                if r["attempts"] == 1 and r["final_outcome"] == "success"
            ) / len(resolved)
        else:
            first_pass = 0.0

        out.append({
            "version": _version_label(v),
            "issues": issues,
            "attempts": attempts,
            "first_pass_rate": first_pass,
            "budget_caps": budget_caps,
            "total_cost_usd": total_cost,
            "mean_cost_per_issue": (total_cost / issues) if issues else 0.0,
        })
    return out
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_bench.py -v`
Expected: all tests pass (19 cumulative).

- [ ] **Step 5: Commit**

```bash
git add bench.py tests/test_bench.py
git commit -m "feat(bench): per-version aggregation (issues, attempts, first_pass_rate, totals)"
```

---

## Task 6: `bench.py` — version-map fetch with GitHub fallback

**Files:**
- Modify: `bench.py`
- Modify: `tests/test_bench.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_bench.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bench.py -k fetch_version_map -v`
Expected: 3 failures — `ImportError: cannot import name 'fetch_version_map'`.

- [ ] **Step 3: Implement `fetch_version_map`**

At the top of `bench.py`, add the import (alongside the existing stdlib imports):

```python
import sys
from github_client import GitHubClient
from versioning import parse_version
```

Then append the function:

```python
def fetch_version_map(config: dict) -> dict[int, tuple[int, int]] | None:
    """Look up issue_number → version tuple via the GitHub Projects API.

    Returns None (with a stderr warning) on any failure: missing project
    config block, missing token, network error, or unexpected payload.
    Callers degrade to issue-only output when the result is None.
    """
    project = config.get("project")
    if not isinstance(project, dict) or "owner" not in project or "number" not in project or "status_field_id" not in project:
        print("[bench] warning: config has no `project` block — version grouping disabled", file=sys.stderr)
        return None

    try:
        gh = GitHubClient()
        gh.load_project_metadata(
            owner=project["owner"],
            project_number=project["number"],
            status_field_id=project["status_field_id"],
        )
        issues = gh.fetch_all_project_issues()
    except Exception as e:  # noqa: BLE001 — broad catch is intentional for graceful degradation
        print(f"[bench] warning: GitHub lookup failed — {e}", file=sys.stderr)
        return None

    out: dict[int, tuple[int, int]] = {}
    for issue in issues:
        v = parse_version(issue.get("title", "") or "")
        if v is not None:
            out[int(issue["number"])] = v
    return out
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_bench.py -k fetch_version_map -v`
Expected: 3 passes.

- [ ] **Step 5: Commit**

```bash
git add bench.py tests/test_bench.py
git commit -m "feat(bench): fetch issue→version map via GitHub Projects, degrade on failure"
```

---

## Task 7: `bench.py` — stdout table renderer

**Files:**
- Modify: `bench.py`
- Modify: `tests/test_bench.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_bench.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bench.py -k render_stdout -v`
Expected: 2 failures — `render_stdout` not defined.

- [ ] **Step 3: Implement `render_stdout`**

Append to `bench.py`:

```python
def _format_pct(x: float) -> str:
    return f"{x*100:.0f}%"


def _format_usd(x: float) -> str:
    return f"${x:.2f}"


def render_stdout(by_version: list[dict], by_issue: list[dict]) -> str:
    """Render the two-table default output.

    Empty input lists are skipped — when version lookup fails the version
    table is absent rather than empty.
    """
    parts: list[str] = []

    if by_version:
        parts.append("=== By version ===")
        header = f"{'version':<10} {'issues':>6} {'attempts':>8} {'first-pass':>10} {'budget-caps':>11} {'total $':>9} {'mean $/issue':>13}"
        parts.append(header)
        for r in by_version:
            parts.append(
                f"{r['version']:<10} {r['issues']:>6} {r['attempts']:>8} "
                f"{_format_pct(r['first_pass_rate']):>10} {r['budget_caps']:>11} "
                f"{_format_usd(r['total_cost_usd']):>9} {_format_usd(r['mean_cost_per_issue']):>13}"
            )
        parts.append("")

    if by_issue:
        parts.append("=== By issue ===")
        header = f"{'issue':>6} {'coding model':<22} {'testing model':<22} {'review model':<22} {'attempts':>8} {'outcome':<22} {'cost':>8}"
        parts.append(header)
        for r in by_issue:
            mu = r["models_used"]
            parts.append(
                f"#{r['issue_number']:<5} "
                f"{(mu.get('coding') or '—'):<22} "
                f"{(mu.get('testing') or '—'):<22} "
                f"{(mu.get('review') or '—'):<22} "
                f"{r['attempts']:>8} "
                f"{r['final_outcome']:<22} "
                f"{_format_usd(r['total_cost_usd']):>8}"
            )

    return "\n".join(parts) + "\n"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_bench.py -k render_stdout -v`
Expected: 2 passes.

- [ ] **Step 5: Commit**

```bash
git add bench.py tests/test_bench.py
git commit -m "feat(bench): stdout two-table renderer"
```

---

## Task 8: `bench.py` — JSON renderer

**Files:**
- Modify: `bench.py`
- Modify: `tests/test_bench.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_bench.py`:

```python
def test_render_json_roundtrips():
    from bench import render_json
    by_version = [{
        "version": "v0.14", "issues": 1, "attempts": 1, "first_pass_rate": 1.0,
        "budget_caps": 0, "total_cost_usd": 1.0, "mean_cost_per_issue": 1.0,
    }]
    by_issue = [{
        "issue_number": 1, "attempts": 1, "budget_caps": 0,
        "models_used": {"coding": "m", "testing": None, "review": None},
        "total_cost_usd": 1.0, "final_outcome": "success",
    }]
    out = render_json(by_version, by_issue)
    parsed = json.loads(out)
    assert parsed["by_version"][0]["version"] == "v0.14"
    assert parsed["by_issue"][0]["issue_number"] == 1
    assert parsed["by_issue"][0]["models_used"]["coding"] == "m"
    assert parsed["by_issue"][0]["models_used"]["testing"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bench.py -k render_json -v`
Expected: FAIL — `render_json` not defined.

- [ ] **Step 3: Implement**

Append to `bench.py`:

```python
def render_json(by_version: list[dict], by_issue: list[dict]) -> str:
    """Render a single JSON document with both tables."""
    return json.dumps({"by_version": by_version, "by_issue": by_issue}, indent=2)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_bench.py -k render_json -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bench.py tests/test_bench.py
git commit -m "feat(bench): JSON renderer"
```

---

## Task 9: `bench.py` — Markdown renderer

**Files:**
- Modify: `bench.py`
- Modify: `tests/test_bench.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_bench.py`:

```python
def test_render_markdown_writes_both_tables_and_header(tmp_path):
    from bench import render_markdown
    by_version = [{
        "version": "v0.14", "issues": 1, "attempts": 1, "first_pass_rate": 1.0,
        "budget_caps": 0, "total_cost_usd": 1.0, "mean_cost_per_issue": 1.0,
    }]
    by_issue = [{
        "issue_number": 1, "attempts": 1, "budget_caps": 0,
        "models_used": {"coding": "claude-sonnet-4-6", "testing": "claude-haiku-4-5",
                        "review": "claude-opus-4-7"},
        "total_cost_usd": 1.0, "final_outcome": "success",
    }]
    out_path = tmp_path / "report.md"
    render_markdown(by_version, by_issue, str(out_path))
    text = out_path.read_text()
    assert text.startswith("# Playbook bench")
    assert "## By version" in text
    assert "## By issue" in text
    assert "| v0.14 |" in text
    assert "| #1 |" in text
    assert "claude-sonnet-4-6" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bench.py -k render_markdown -v`
Expected: FAIL — `render_markdown` not defined.

- [ ] **Step 3: Implement**

Append to `bench.py`:

```python
from datetime import datetime, timezone  # add to imports if not already present


def render_markdown(by_version: list[dict], by_issue: list[dict], path: str) -> None:
    """Write a GitHub-flavored Markdown report to `path`. Overwrites if present."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = [f"# Playbook bench — generated {today}", ""]

    if by_version:
        lines.append("## By version")
        lines.append("")
        lines.append("| version | issues | attempts | first-pass | budget-caps | total | mean/issue |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in by_version:
            lines.append(
                f"| {r['version']} | {r['issues']} | {r['attempts']} | "
                f"{_format_pct(r['first_pass_rate'])} | {r['budget_caps']} | "
                f"{_format_usd(r['total_cost_usd'])} | {_format_usd(r['mean_cost_per_issue'])} |"
            )
        lines.append("")

    if by_issue:
        lines.append("## By issue")
        lines.append("")
        lines.append("| issue | coding | testing | review | attempts | outcome | cost |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in by_issue:
            mu = r["models_used"]
            lines.append(
                f"| #{r['issue_number']} | "
                f"{mu.get('coding') or '—'} | "
                f"{mu.get('testing') or '—'} | "
                f"{mu.get('review') or '—'} | "
                f"{r['attempts']} | {r['final_outcome']} | "
                f"{_format_usd(r['total_cost_usd'])} |"
            )
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_bench.py -k render_markdown -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bench.py tests/test_bench.py
git commit -m "feat(bench): markdown renderer"
```

---

## Task 10: `bench.py` — CLI entry point + flags

**Files:**
- Modify: `bench.py`
- Modify: `tests/test_bench.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_bench.py`:

```python
def test_main_smoke_default(tmp_path, monkeypatch, capsys):
    """Run main() in a project dir with one log; default invocation prints the issue table."""
    from bench import main as bench_main

    # Project dir with playbook.yaml + .playbook/logs/<fixture>
    project = tmp_path / "proj"
    (project / ".playbook" / "logs").mkdir(parents=True)
    (project / "playbook.yaml").write_text("repo: owner/repo\n")
    _copy_fixture("coding_success.json",
                  project / ".playbook" / "logs" / "owner-repo-42-coding-20260514T024012.json")

    monkeypatch.chdir(project)
    # No 'project' block in playbook.yaml → fetch_version_map returns None → issue-only table.
    monkeypatch.setattr("sys.argv", ["bench"])
    rc = bench_main()
    out = capsys.readouterr().out
    assert "=== By issue ===" in out
    assert "#42" in out
    assert rc == 0


def test_main_by_issue_and_by_version_mutually_exclusive(monkeypatch, capsys):
    from bench import main as bench_main
    monkeypatch.setattr("sys.argv", ["bench", "--by-issue", "--by-version"])
    rc = bench_main()
    assert rc == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err.lower()


def test_main_since_filter(tmp_path, monkeypatch, capsys):
    """`--since v0.14` excludes issues from v0.13."""
    from bench import main as bench_main
    project = tmp_path / "proj"
    (project / ".playbook" / "logs").mkdir(parents=True)
    (project / "playbook.yaml").write_text("repo: owner/repo\n")
    _copy_fixture("coding_success.json",
                  project / ".playbook" / "logs" / "owner-repo-261-coding-20260514T024012.json")
    _copy_fixture("coding_success.json",
                  project / ".playbook" / "logs" / "owner-repo-269-coding-20260514T030000.json")
    monkeypatch.chdir(project)

    # Mock GitHub so we get a real version map
    with patch("bench.GitHubClient") as MockGH:
        MockGH.return_value.fetch_all_project_issues.return_value = [
            {"number": 261, "title": "[v0.13] x"},
            {"number": 269, "title": "[v0.15] y"},
        ]
        monkeypatch.setattr(
            "sys.argv",
            ["bench", "--since", "v0.14"],
        )
        # Also stub the project block check
        import yaml
        (project / "playbook.yaml").write_text(yaml.safe_dump({
            "repo": "owner/repo",
            "project": {"owner": "owner", "number": 1, "status_field_id": "x"},
        }))
        rc = bench_main()
    out = capsys.readouterr().out
    assert "v0.15" in out
    assert "v0.13" not in out
    assert rc == 0


def test_main_json_output(tmp_path, monkeypatch, capsys):
    from bench import main as bench_main
    project = tmp_path / "proj"
    (project / ".playbook" / "logs").mkdir(parents=True)
    (project / "playbook.yaml").write_text("repo: owner/repo\n")
    _copy_fixture("coding_success.json",
                  project / ".playbook" / "logs" / "owner-repo-42-coding-20260514T024012.json")
    monkeypatch.chdir(project)
    monkeypatch.setattr("sys.argv", ["bench", "--json"])
    rc = bench_main()
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "by_issue" in parsed and "by_version" in parsed
    assert rc == 0


def test_main_markdown_output(tmp_path, monkeypatch, capsys):
    from bench import main as bench_main
    project = tmp_path / "proj"
    (project / ".playbook" / "logs").mkdir(parents=True)
    (project / "playbook.yaml").write_text("repo: owner/repo\n")
    _copy_fixture("coding_success.json",
                  project / ".playbook" / "logs" / "owner-repo-42-coding-20260514T024012.json")
    md_out = tmp_path / "bench.md"
    monkeypatch.chdir(project)
    monkeypatch.setattr("sys.argv", ["bench", "--markdown", str(md_out)])
    rc = bench_main()
    assert rc == 0
    text = md_out.read_text()
    assert "# Playbook bench" in text
    assert "## By issue" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bench.py -k main -v`
Expected: 5 failures — `main` not defined.

- [ ] **Step 3: Implement `main`**

Append to `bench.py`:

```python
import argparse
import glob
from config import load_config


def _filter_by_since(by_version: list[dict], since: tuple[int, int] | None) -> list[dict]:
    if since is None:
        return by_version
    out = []
    for r in by_version:
        v = r["version"]
        if v == "(no version)":
            continue
        if v == "bootstrap":
            tup = (0, 0)
        else:
            m = re.match(r"^v(\d+)\.(\d+)$", v)
            if not m:
                continue
            tup = (int(m.group(1)), int(m.group(2)))
        if tup >= since:
            out.append(r)
    return out


def _parse_since(s: str) -> tuple[int, int]:
    m = re.match(r"^v(\d+)\.(\d+)$", s)
    if not m:
        raise argparse.ArgumentTypeError(f"--since must look like 'v0.14', got: {s!r}")
    return (int(m.group(1)), int(m.group(2)))


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="bench",
        description="Aggregate .playbook/logs/*.json into cost/quality tables.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    parser.add_argument("--markdown", metavar="PATH", help="Write markdown report to PATH.")
    parser.add_argument("--since", type=_parse_since, default=None,
                        help="Filter to versions >= vX.Y (e.g. v0.14).")
    parser.add_argument("--by-issue", action="store_true",
                        help="Suppress the per-version table.")
    parser.add_argument("--by-version", action="store_true",
                        help="Suppress the per-issue table.")
    args = parser.parse_args()

    if args.by_issue and args.by_version:
        print("[bench] error: --by-issue and --by-version are mutually exclusive",
              file=sys.stderr)
        return 2

    # 1. Discover logs
    log_paths = sorted(glob.glob(os.path.join(".playbook", "logs", "*.json")))

    # 2. Extract rows
    rows: list[dict] = []
    for p in log_paths:
        row = extract_log_row(p)
        if row is not None:
            rows.append(row)

    # 3. Per-issue aggregation
    by_issue = aggregate_by_issue(rows)

    # 4. Per-version aggregation (best-effort GitHub lookup)
    try:
        config = load_config()
    except FileNotFoundError:
        config = {}
    version_map = fetch_version_map(config) if config else None
    if version_map is not None:
        by_version = aggregate_by_version(by_issue, version_map)
        by_version = _filter_by_since(by_version, args.since)
    else:
        by_version = []

    # 5. Apply table suppression flags
    if args.by_issue:
        by_version = []
    if args.by_version:
        by_issue = []

    # 6. Render
    if args.json:
        print(render_json(by_version, by_issue))
    elif args.markdown:
        render_markdown(by_version, by_issue, args.markdown)
    else:
        print(render_stdout(by_version, by_issue), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_bench.py -k main -v`
Expected: 5 passes.

- [ ] **Step 5: Run full bench test file**

Run: `pytest tests/test_bench.py -v`
Expected: all bench tests pass (~30 cumulative).

- [ ] **Step 6: Commit**

```bash
git add bench.py tests/test_bench.py
git commit -m "feat(bench): main entry point with --json, --markdown, --since, --by-* flags"
```

---

## Final verification

- [ ] **Step 1: Full test suite green**

Run: `pytest tests/ -v 2>&1 | tail -10`
Expected: all green, no failures.

- [ ] **Step 2: Lint passes**

Run: `ruff check .`
Expected: no errors (or only pre-existing unrelated warnings).

- [ ] **Step 3: Smoke test against real logs**

```bash
cd /home/bryang/Dev_Space/bee_gee_games/godot/paint-ballas-auto
PYTHONPATH=/home/bryang/Dev_Space/playbook python3 -m bench --since v0.11 | head -40
```

Expected: two tables print — the per-version table includes v0.11 through v0.15 with non-zero cost and attempts; the per-issue table lists each issue with its model and attempts. Some legacy logs (pre-Task-1) will show `agent_role` filled in by the heuristic.

- [ ] **Step 4: Verify --markdown writes a usable report**

```bash
cd /home/bryang/Dev_Space/bee_gee_games/godot/paint-ballas-auto
PYTHONPATH=/home/bryang/Dev_Space/playbook python3 -m bench --markdown /tmp/bench-baseline.md
head -20 /tmp/bench-baseline.md
```

Expected: a markdown file with `# Playbook bench — generated <today>`, both table headers, at least one row per version.

- [ ] **Step 5: Open PR**

```bash
git push -u origin <current-branch>
gh pr create --title "feat: python3 -m bench — cost/quality benchmark over agent logs" \
  --body "Implements docs/specs/2026-05-14-model-tiering-and-bench-design.md PR 2.

Adds a top-level \`bench.py\` module invoked as \`PYTHONPATH=… python3 -m bench\`
from a project repo. Reads \`.playbook/logs/*.json\` and prints per-issue +
per-version cost and cheap-quality-proxy tables, with GitHub-issue-title →
version mapping when reachable.

Output formats: default stdout, \`--json\` (machine-readable), \`--markdown
PATH\` (committable report). Filters: \`--since vX.Y\`, \`--by-issue\` /
\`--by-version\` (mutually exclusive).

Quality proxies: per-issue attempt count, per-issue budget-cap count,
per-version first-pass success rate (resolved issues only).

Also bumps \`state.log_path\` to include the agent_type segment so future
logs don't need the legacy role-inference heuristic.

Test coverage: ~30 new tests across extraction, aggregation, GitHub
fallback, three renderers, and CLI flag handling."
```
