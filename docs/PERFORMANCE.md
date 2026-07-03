# Performance Tuning Guide

## 1. Performance Targets

| Metric | Target | Measured by |
|---|---|---|
| **Cold start** (app → ready) | ≤ 1.5 s | `tnt perf` startup phase |
| **Hotkey → window visible** | ≤ 100 ms | Performance tab "hotkey_latency" |
| **LLM response cache hit** | ≤ 5 ms | `test_performance_targets.py::TestLLMCacheHitLatency` |
| **Control tree cache hit** | ≤ 1 ms | `test_performance_targets.py::TestControlTreeCacheHitLatency` |
| **Memory (idle)** | ≤ 250 MB RSS | Performance tab memory snapshot |
| **Memory (during task)** | ≤ 600 MB RSS | Performance tab memory snapshot |

Cold start means the time from launching `tnt` (or the GUI shell) to the tray
icon appearing and the app accepting hotkey input. Background initialisation
(model loading, window pre-warming) may continue after this point but must
not block the critical path.

## 2. How to Read the Performance Tab

The Performance tab (available in the GUI main window) plots live and
historical metrics.

| Chart | X-axis | Y-axis | What to look for |
|---|---|---|---|
| **LLM call duration** | Time | ms per call | Spikes > 5 s indicate network issues or rate-limiting |
| **LLM cache hit rate** | Time | % | Should be > 80 % during repetitive tasks; low values suggest TTL too short |
| **Control tree fetch** | Time | ms per fetch | > 50 ms suggests a slow UIA enumeration (large or complex window) |
| **Memory RSS** | Time | MB | Gradual increase may indicate a leak; flat line is healthy |
| **Hotkey → show** | Time | ms | > 100 ms suggests event-loop congestion |
| **Phase breakdown** | Task step | ms | Identifies which ReAct phase (think, tool call, LLM wait) dominates |

Each chart shows a rolling 5-minute window with 1-second resolution. Click
any data point to see the raw metric row in the detail panel below.

## 3. Common Bottlenecks

### LLM Latency

The largest contributor to task time is waiting for the LLM. Mitigations:

- **Enable the LLM response cache** (`cache.llm_enabled=true`) — identical
  requests within the TTL window return instantly.
- **Use `deepseek-flash`** instead of `deepseek-chat` for a ~3× speedup
  on simple tasks.
- **Reduce max_tokens_per_call** (default 2048) if the LLM routinely
  produces long but repetitive output.
- **Check network latency**: run `tnt perf --phase llm` to see
  round-trip times.

### UIA Enumeration

Calling `get_control_tree` on a complex window (e.g. a web browser with
hundreds of elements) can take 100–500 ms. Mitigations:

- **Enable the control tree cache** (`cache.control_tree_enabled=true`,
  default 3 s TTL).
- **Call `invalidate_on_action` only when needed** — after a click or
  type that you *know* changed the tree. Avoid blanket invalidation.
- **Filter by control type** when possible (e.g. only `Button` and
  `Edit` controls) to reduce tree depth.

### Hot Path Overhead

Every tool dispatch and planner step incurs fixed overhead:

- **Instrumentation**: each `record()` call is O(1), but 10 000 points
  in the buffer takes ~100 KB of memory. Keep `max_points` at 10 000
  unless profiling deep history.
- **Logging**: loguru is async by default, but `logger.debug()` calls
  in hot loops still format strings. Reduce log level to `WARNING` in
  production: `loguru.logger.remove(); loguru.logger.add(sink, level="WARNING")`.

## 4. Tuning Knobs

All knobs are in the config file (TOML, loaded by `ConfigStore`):

| Key | Default | Range | Effect |
|---|---|---|---|
| `cache.llm_enabled` | `true` | bool | Enable/disable LLM response cache |
| `cache.llm_ttl_s` | `300` | 0–3600 | Seconds to keep a cached LLM response |
| `cache.control_tree_enabled` | `true` | bool | Enable/disable control tree cache |
| `cache.control_tree_ttl_s` | `3` | 0–60 | Seconds before a cached tree is stale |
| `perf.flush_interval_s` | `30` | 5–300 | How often to flush in-memory metrics to `perf.jsonl` |
| `perf.max_points` | `10000` | 1000–100000 | Ring buffer capacity for in-memory metrics |
| `history.max_entries` | `500` | 50–5000 | Max history records before rotation |
| `history.rotation_policy` | `"keep_recent"` | `keep_recent`, `archive` | What to do when history is full |

## 5. When to Disable Caching

Disable caching in these scenarios:

- **Security-sensitive contexts**: If the user runs TNT in a context where
  LLM responses contain sensitive data (PII, credentials), disable the LLM
  cache to ensure responses are never reused across calls.
- **Debugging stale behaviour**: If you suspect the agent is acting on
  outdated UI state, disable the control tree cache temporarily.
- **Testing**: Set both caches to `enabled=false` in test environments to
  ensure tests always exercise the full path.

To disable from the CLI, edit the config file:

```toml
[cache]
llm_enabled = false
control_tree_enabled = false
```

## 6. Profiling a Slow Task

Use the CLI profiling tools to identify slow phases:

```bash
# Run a task and show phase-level timing
tnt perf --task "Open Notepad and type Hello"

# Tail live metrics (updates every second)
tnt perf-tail

# Export metrics to a file for offline analysis
tnt perf --export perf_export.jsonl
```

Steps to diagnose a slow task:

1. **Run `tnt perf --task "..."`** and note the phase breakdown.
2. **If LLM phase is dominant**: check cache hit rate in the Performance
   tab. If low, increase `cache.llm_ttl_s` or verify the task is not
   generating unique prompts each step.
3. **If tool phase is dominant**: identify which tool is slow via the
   per-tool breakdown. Common culprits: `get_control_tree` (slow UIA),
   `launch_app` (process start), `wait_for_window` (timeout).
4. **If idle time between phases**: check event-loop congestion. Open
   the Performance tab and look at the "hotkey → show" chart — if it
   spikes during task execution, the Qt event loop may be starved.
5. **Memory growing**: take a baseline memory snapshot (`tnt perf --snapshot`),
   run the task, and compare. A delta > 50 MB may indicate a leak.

The `tnt perf-tail` command is especially useful for real-time diagnosis.
It polls `perf.jsonl` every second and prints new metric rows to stdout,
highlighting values that exceed their target threshold.
