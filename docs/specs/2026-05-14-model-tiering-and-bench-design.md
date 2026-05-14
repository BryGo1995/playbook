# Model Tiering for Agents + Cost/Quality Benchmark — Design

## Motivation

Every dispatched agent today inherits the user's `claude` CLI default model — currently Opus 4.7 across coding, testing, and review. Logs from issue #271 on `paint-ballas-auto` show the cost shape: 101 turns, 10.47M cache-read tokens, **$5.05 per attempt**, hit the per-attempt USD cap before producing a PR. Two attempts later the issue auto-blocked under the tiered budget-cap retry policy from PR #17.

Opus is overkill for two of the three roles. Testing largely runs the existing suite and reports back — Haiku-class reasoning is sufficient. Review reads a diff and writes structured feedback — Opus earns its cost here. Coding is the only role that genuinely needs frontier reasoning, and Sonnet 4.6 is the established sweet spot for autonomous coding at roughly 5× cheaper per token.

A model swap is high-leverage but blind without measurement. Without a way to compare before/after at the issue and version granularity, "Sonnet is cheaper" stays a hypothesis. The agent SDK already writes per-attempt cost into the NDJSON terminal `result` record (`type:"result"`, `total_cost_usd`, `num_turns`, `subtype`); the orchestrator already emits per-issue attempt comments. The raw data exists. What's missing is the read path.

This design adds two independent changes:

1. **PR 1 — Model tiering.** Configurable model per agent role in `defaults.yaml`, threaded through to `claude -p --model <id>`. Pinned full model IDs (no aliases) so historical comparisons stay stable when Anthropic ships a new minor.
2. **PR 2 — Bench script.** A read-only `python3 -m bench` invocation that aggregates `.playbook/logs/*.json` into per-issue and per-version cost+quality tables. Cheap quality proxies (attempt count, budget-cap rate, first-pass rate) only — test-pass parsing deferred until a v2 if needed.

## Goals

- Each agent role uses a configurable model. Defaults: Sonnet 4.6 for coding, Haiku 4.5 for testing, Opus 4.7 for review.
- A user running `python3 -m bench` from a project repo gets a per-issue + per-version cost/quality table from existing logs.
- Bench works on logs predating model tiering (legacy filename schema, no model variation).
- Bench groups by version when GitHub is reachable; degrades to issue-only grouping when not.
- Backward compatible: an install whose merged config omits the `models:` block emits no `--model` flag and behaves identically to today.

## Non-goals

- Per-role budget overrides. Existing `coding_max_budget_usd` stays at top level; `testing_max_budget_usd` / `review_max_budget_usd` are not introduced. YAGNI — testing and review have never approached their implicit cap.
- Fallback models (`--fallback-model`). Deliberately omitted — fallbacks introduce variance that contaminates benchmarks.
- Auto-promotion: bench does not make decisions. It prints numbers; the human decides whether to swap models again.
- Parsing test-runner output (`pytest`/`unittest`/`godot --test`/etc.) for pass/fail rates. Too fragile across project conventions. Deferred to a possible `--with-tests` v2 once a stable signal source is identified.
- Writing into the existing `metrics/vX.Y.md` schema from `docs/metrics-format.md`. That file lives in the *project* repo and is written by gameplan/film-room skills; bench writes to wherever its `--markdown PATH` argument points. Coupling is intentionally loose.
- Replacing manual "is this code good?" judgment. Bench surfaces proxies, not verdicts.

## Architecture

### PR 1 — Model tiering

**Config (`defaults.yaml`):**

```yaml
models:
  coding:  claude-sonnet-4-6
  testing: claude-haiku-4-5
  review:  claude-opus-4-7
```

Per-project `playbook.yaml` may override any subset. Existing `load_config` merge logic is unchanged.

**Plumbing:**

| File | Change |
|---|---|
| `agents/base.py` | `build_claude_command` gains optional `model: str \| None = None`. When non-None, argv gains `["--model", model]` after the existing `--max-budget-usd` segment. When `None`, no flag emitted. |
| `agents/coding.py` | `CodingAgent.build_command` gains `model` pass-through; default `None`. |
| `agents/testing.py` | Same. |
| `agents/review.py` | Same. |
| `orchestrator.py` | Each of `_dispatch_coding`, `_dispatch_testing`, `_dispatch_review` reads `self.config.get("models", {}).get("<role>")` and passes it to the agent's `build_command`. `.get` fallback degrades gracefully to "no flag" rather than `KeyError`. |

**Backward compatibility.** An install whose merged config lacks `models:` (or has `models: { coding: ... }` only) gets `None` for the missing roles. `None` → no `--model` flag → CLI uses its default. Identical to today's behavior.

**Distribution surface.** `defaults.yaml` ships in the playbook repo. The chosen model IDs become public defaults for any downstream user. Per the project's distribution principle, the chosen IDs are family-canonical (latest minor of each family as of the spec date), not maintainer-specific.

### PR 2 — Bench script

**Upstream change to enable role tagging in new logs (`state.py`, 3 LOC):**

```python
def log_path(self, repo: str, issue_number: int, agent_type: str) -> str:
    safe_repo = repo.replace("/", "-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return os.path.join(self.logs_dir, f"{safe_repo}-{issue_number}-{agent_type}-{timestamp}.json")
```

Filenames go from `<repo>-<issue>-<ts>.json` → `<repo>-<issue>-<role>-<ts>.json`. The three `_dispatch_*` sites in `orchestrator.py` pass their respective role string. Legacy logs without the role segment continue to parse — bench detects role via tool-usage heuristic for them.

**Bench module (`bench.py`, top-level, ~180 LOC):**

Invocation pattern mirrors `summary.py`:

```
cd ~/my-project && PYTHONPATH=/path/to/playbook python3 -m bench [flags]
```

Reads `.playbook/logs/*.json` from cwd. Reads `playbook.yaml` from cwd for project/repo identifiers. One network call (GitHub project items) for version grouping; degrades to issue-only if it fails.

**Per-log extraction (offline):**

| Field | Source |
|---|---|
| `model` | First `init` record's `model` key; `"(unknown)"` if absent |
| `agent_role` | Filename role segment if present. Else, heuristic over observed `tool_use` blocks, applied in this order: (1) any `mcp__github__pull_request_*` → `review`; (2) any `Edit` or `Write` → `coding`; (3) only `Read`/`Bash`/`Grep`/`Glob` → `testing`; (4) otherwise `unknown`. |
| `cost_usd` | Terminal `result.total_cost_usd` |
| `turns` | Terminal `result.num_turns` |
| `cache_read_tokens` | Sum of `message.usage.cache_read_input_tokens` across all assistant turns |
| `output_tokens` | Sum of `message.usage.output_tokens` |
| `outcome` | Terminal `result.subtype` (e.g. `success`, `error_max_budget_usd`, `error_during_execution`) |
| `issue_number` | Parsed from filename |
| `attempt_index` | 1-based position when sorted by timestamp within `(issue_number, agent_role)` |
| `timestamp` | Parsed from filename |

**Per-issue aggregate (one row per issue):**

- `attempts` = count of coding-role logs for that issue (testing/review run at most once per pipeline pass)
- `budget_caps` = count of attempts with `outcome == "error_max_budget_usd"`
- `models_used` = ordered tuple of (coding_model, testing_model, review_model); each `None` if no log for that role
- `total_cost_usd` = sum across all logs for the issue
- `final_outcome` = outcome of the last (latest-timestamp) coding-role log

**Per-version aggregate (one row per version):**

- Joined to issue rows via GitHub-issue-title → `versioning.parse_version`.
- `issues` = count of distinct issue numbers in that version
- `attempts` = sum of per-issue `attempts`
- `first_pass_rate` = fraction of issues with `attempts == 1` and `final_outcome == "success"`. Issues still in flight (no successful outcome on any coding log yet) are excluded from the denominator.
- `budget_caps` = sum of per-issue `budget_caps`
- `total_cost_usd` = sum of per-issue `total_cost_usd`
- `mean_cost_per_issue` = `total_cost_usd / issues`

**Version grouping path:**

```
read playbook.yaml → owner, project.number, repo
  → GitHubClient.fetch_all_project_issues()
  → {issue_number: parse_version(title)}
  → join to issue rows
on failure (no token, network error, missing config):
  print warning to stderr; produce issue-only table; skip the per-version table
```

**Outputs:**

- Default (no flags): two-table stdout — `=== By version ===` then `=== By issue ===`, plain monospace alignment.
- `--json`: single JSON document with two keys `by_version`, `by_issue`, each a list of row dicts.
- `--markdown PATH`: GitHub-flavored markdown file with the same two tables and a `# Playbook bench — generated YYYY-MM-DD` header. Overwrites if `PATH` exists.
- `--since vX.Y`: filter to versions ≥ `(X, Y)`; bootstrap (`(0, 0)`) included only if `--since v0.0`.
- `--by-issue` / `--by-version`: suppress the other table. Mutually exclusive — passing both exits 2 with a usage error.

### Module boundaries

- `agents/base.py` knows about CLI flags. Doesn't import config.
- `agents/*.py` knows about prompts and per-role tool sets. Receives model as a string.
- `orchestrator.py` knows about config shape and dispatch. The only file that maps `config["models"]["<role>"]` → agent constructor.
- `state.py` knows about log paths. Single change site for the filename schema.
- `bench.py` knows about log parsing and table rendering. Imports `versioning.parse_version` and `github_client.GitHubClient`; no other playbook imports.

A consumer of any one of these should be able to understand it without reading the others.

## Testing

### PR 1 — Model tiering

| Test | Assertion |
|---|---|
| `tests/test_agents_base.py::test_build_claude_command_adds_model_flag` | argv contains `["--model", "claude-sonnet-4-6"]` after `--max-budget-usd 5.0` |
| `tests/test_agents_base.py::test_build_claude_command_omits_model_flag_when_none` | `--model` absent from argv |
| `tests/test_agents_coding.py::test_build_command_passes_model` | `model` kwarg reaches `build_claude_command` |
| `tests/test_agents_testing.py::test_build_command_passes_model` | Same shape. |
| `tests/test_agents_review.py::test_build_command_passes_model` | Same shape. |
| `tests/test_orchestrator.py::test_dispatch_uses_role_specific_model` | Three dispatches with patched subprocess → each invocation's argv has the right `--model <id>` for its role. |
| `tests/test_orchestrator.py::test_dispatch_falls_back_when_models_block_missing` | Config without `models:` → no `--model` flag in argv; no exception. |
| `tests/test_config.py::test_models_block_in_defaults` | `load_config()` against `defaults.yaml` exposes `["models"]["coding"]` as `"claude-sonnet-4-6"`. |

### PR 2 — Bench script

Fixtures: `tests/fixtures/bench_logs/` containing crafted NDJSON files covering coding-success, coding-budget-cap, testing-success, review-success, legacy-filename-coding, and a corrupt-JSON-line file.

| Test | Assertion |
|---|---|
| `test_state_log_path_includes_agent_type` | `log_path(repo, n, "coding")` → filename contains `"-coding-"`. |
| `test_bench_extract_coding_success` | Fields populated as spec'd; `outcome == "success"`. |
| `test_bench_extract_budget_cap` | `outcome == "error_max_budget_usd"`. |
| `test_bench_role_from_filename` | New-format filename → role from segment, not heuristic. |
| `test_bench_role_heuristic_coding` | Legacy filename with Edit+Write tool usage → `coding`. |
| `test_bench_role_heuristic_testing` | Legacy filename, only Read+Bash → `testing`. |
| `test_bench_role_heuristic_review` | Legacy filename, github MCP tool usage → `review`. |
| `test_bench_aggregate_per_issue` | Multiple logs for one issue → attempts count + total_cost_usd correct. |
| `test_bench_aggregate_per_version` | Multi-issue version → `first_pass_rate`, `budget_caps`, sums correct. |
| `test_bench_version_lookup_failure_degrades` | Mocked `GitHubClient.fetch_all_project_issues` raises → bench prints warning, produces issue-only table, exits 0. |
| `test_bench_corrupt_log_skipped` | One bad NDJSON file → other rows still produced; warning printed. |
| `test_bench_stdout_default` | Stdout contains both `=== By version ===` and `=== By issue ===`. |
| `test_bench_json_output` | `--json` output round-trips through `json.loads`, has `by_version` and `by_issue` keys. |
| `test_bench_markdown_output` | `--markdown <tmppath>` writes a file containing both table headers and the date stamp. |
| `test_bench_since_filter` | `--since v0.14` excludes v0.11–v0.13 rows. |

Suite addition: ~15-18 tests, ~250 lines. Existing suite stays ≪ 1s wall.

## Alternatives considered

- **Aliases (`sonnet`/`haiku`/`opus`) instead of pinned IDs.** Convenient but the benchmark baseline silently shifts when Anthropic releases a new minor. Rejected for the project's stated benchmarking goal; pinned IDs win.
- **Per-role budget overrides in config.** Would let testing/review carry tighter caps than coding. Real, but never needed in practice today — only coding has hit its cap. Deferred until data justifies it.
- **Subsuming bench into `summary.py`.** Reuses an existing cron-wired entry point. Rejected because the two have different consumers (Slack digest vs. cost/quality report) and different output shapes; muddying summary's responsibility hurts both.
- **Writing bench output into `metrics/vX.Y.md`.** The existing schema in `docs/metrics-format.md` is gameplan/film-room's territory. Tying bench to that emission requires also fixing the missing-emission issue in `paint-ballas-auto`. Loose coupling via `--markdown PATH` keeps bench independent.
- **Parsing testing-agent NDJSON for pass/fail counts in v1.** Considered for first-class quality proxy. Rejected — each project's test runner formats output differently (pytest vs unittest vs godot's headless mode vs custom), so any parser is fragile across the distribution surface. Cheaper proxies (attempt count, budget-cap rate) are runner-agnostic.
- **Always-on per-attempt JSON sidecar emitted by the orchestrator.** Would simplify bench by removing all NDJSON parsing. Real, but doubles the disk footprint and adds a second source of truth that can drift from the SDK's own log. Rejected; the SDK log is already authoritative.
