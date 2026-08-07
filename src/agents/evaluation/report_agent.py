"""
agents/report_agent.py — STAGE 4 (optional): REPORT

Reads results.json (the Execute stage's output), plus test_plan.json and
map_store.json for extra context, and writes a single self-contained HTML
scan report under config.REPORT_DIR (defaults to "reports/", matching the
folder already present in this project).

This is intentionally a separate, optional stage rather than something
bolted onto execute_all(): you can re-generate a report from an existing
results.json at any time, without re-running the game, via:

    python main.py --report
"""
import json
import os
from datetime import datetime

import src.core.config as config

RESULTS_FILE = "outputs/results/results.json"
PLAN_FILE    = "outputs/results/test_plan.json"
MAP_FILE     = "outputs/results/map_store.json"
REPORTS_DIR  = getattr(config, "REPORT_DIR", "reports")

_VERDICT_COLOR = {"PASS": "#1f8a3b", "PARTIAL": "#b8860b", "FAIL": "#c0392b", "ERROR": "#7f1d1d"}
_VERDICT_BG    = {"PASS": "#e8f7ec", "PARTIAL": "#fdf3da", "FAIL": "#fbe9e7", "ERROR": "#f3dede"}


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _fmt_duration(start_iso, end_iso) -> str:
    if not start_iso or not end_iso:
        return "-"
    try:
        t0, t1 = datetime.fromisoformat(start_iso), datetime.fromisoformat(end_iso)
        secs = (t1 - t0).total_seconds()
        if secs < 60:
            return f"{secs:.0f}s"
        m, s = divmod(int(secs), 60)
        return f"{m}m {s}s"
    except Exception:
        return "-"


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                  .replace(">", "&gt;").replace('"', "&quot;"))


def generate_json_report() -> str:
    """Build a structured JSON scan report (run metadata + summary + per-scenario
    results) under REPORTS_DIR. Distinct from the raw results.json: this is a
    self-contained report artifact with counts, map coverage, and durations.
    Returns the output path, or None if results.json doesn't exist yet.

    (CSV and Jira export will read this same structure later.)
    """
    results = _load_json(RESULTS_FILE, None)
    if results is None:
        print(f"ERROR: {RESULTS_FILE} not found. Run the execute stage first.")
        return None

    plan = _load_json(PLAN_FILE, {})
    mp = _load_json(MAP_FILE, {})

    counts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0, "INCONCLUSIVE": 0, "ERROR": 0}
    for r in results:
        v = r.get("verdict", "ERROR")
        counts[v] = counts.get(v, 0) + 1

    report = {
        "game": plan.get("game", "Unknown Game"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": getattr(config, "DECIDER_MODEL", "unknown"),
        "summary": {
            "total": len(results),
            "pass": counts["PASS"],
            "partial": counts["PARTIAL"],
            "fail": counts["FAIL"],
            "inconclusive": counts["INCONCLUSIVE"],
            "error": counts["ERROR"],
        },
        "map_coverage": {
            "screens": len(mp.get("nodes", {})),
            "edges": len(mp.get("edges", [])),
        },
        "results": [
            {
                "id": r.get("id", ""),
                "category": r.get("category", ""),
                "title": r.get("title", ""),
                "verdict": r.get("verdict", "ERROR"),
                "metrics": r.get("metrics", {}) or {},
                "logs": r.get("logs", []) or [],
                "duration": _fmt_duration(r.get("start_time"), r.get("end_time")),
                "start_time": r.get("start_time"),
                "end_time": r.get("end_time"),
            }
            for r in results
        ],
    }

    os.makedirs(REPORTS_DIR, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(REPORTS_DIR, f"scan_report_{run_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"JSON report written -> {out_path}")
    return out_path


def generate_report() -> str:
    """Build the JSON scan report (primary), plus the HTML view. Returns the
    HTML path for backward compatibility, or None if results.json is missing."""
    # JSON report is the primary artifact now (CSV/Jira will build on it later).
    generate_json_report()
    # -- HTML view (unchanged) --
    results = _load_json(RESULTS_FILE, None)
    if results is None:
        print(f"ERROR: {RESULTS_FILE} not found. Run the execute stage first.")
        return None

    plan = _load_json(PLAN_FILE, {})
    game = plan.get("game", "Unknown Game")
    mp = _load_json(MAP_FILE, {})
    screens_mapped = len(mp.get("nodes", {}))
    edges_mapped = len(mp.get("edges", []))

    counts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0, "ERROR": 0}
    for r in results:
        v = r.get("verdict", "ERROR")
        counts[v] = counts.get(v, 0) + 1
    total = len(results)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(REPORTS_DIR, f"scan_report_{run_id}.html")

    rows = []
    for r in results:
        v = r.get("verdict", "ERROR")
        color, bg = _VERDICT_COLOR.get(v, "#444"), _VERDICT_BG.get(v, "#eee")
        metrics = r.get("metrics", {}) or {}
        metrics_str = ", ".join(f"{k}={mv}" for k, mv in metrics.items()) or "-"
        logs_str = "\n".join(_esc(l) for l in (r.get("logs") or [])) or "-"
        duration = _fmt_duration(r.get("start_time"), r.get("end_time"))
        rows.append(
            f'<tr style="background:{bg}">'
            f"<td>{_esc(r.get('id',''))}</td>"
            f"<td>{_esc(r.get('category',''))}</td>"
            f"<td>{_esc(r.get('title',''))}</td>"
            f'<td style="color:{color};font-weight:700">{_esc(v)}</td>'
            f"<td>{_esc(metrics_str)}</td>"
            f"<td>{logs_str}</td>"
            f"<td>{duration}</td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(game)} - QA Scan Report</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
          margin: 0; padding: 32px; background: #f7f7f8; color: #1d1d1f; }}
  h1 {{ margin: 0 0 4px 0; font-size: 22px; }}
  .sub {{ color: #666; margin-bottom: 24px; font-size: 13px; }}
  .summary {{ display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }}
  .card {{ background: #fff; border-radius: 10px; padding: 16px 22px;
           box-shadow: 0 1px 3px rgba(0,0,0,.08); min-width: 100px; }}
  .card .n {{ font-size: 28px; font-weight: 700; }}
  .card .l {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: .04em; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  th, td {{ text-align: left; padding: 10px 12px; font-size: 13px;
            border-bottom: 1px solid #eee; vertical-align: top; }}
  th {{ background: #fafafa; text-transform: uppercase; font-size: 11px;
        color: #666; letter-spacing: .04em; }}
  .meta {{ margin-top: 24px; font-size: 12px; color: #888; }}
</style>
</head>
<body>
  <h1>{_esc(game)} - QA Scan Report</h1>
  <div class="sub">Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | model={_esc(config.DECIDER_MODEL)}</div>

  <div class="summary">
    <div class="card"><div class="n">{total}</div><div class="l">Total</div></div>
    <div class="card" style="color:{_VERDICT_COLOR['PASS']}"><div class="n">{counts['PASS']}</div><div class="l">Pass</div></div>
    <div class="card" style="color:{_VERDICT_COLOR['PARTIAL']}"><div class="n">{counts['PARTIAL']}</div><div class="l">Partial</div></div>
    <div class="card" style="color:{_VERDICT_COLOR['FAIL']}"><div class="n">{counts['FAIL']}</div><div class="l">Fail</div></div>
    <div class="card" style="color:{_VERDICT_COLOR['ERROR']}"><div class="n">{counts['ERROR']}</div><div class="l">Error</div></div>
  </div>

  <table>
    <thead>
      <tr><th>ID</th><th>Category</th><th>Title</th><th>Verdict</th><th>Metrics</th><th>Notes</th><th>Duration</th></tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>

  <div class="meta">Map coverage: {screens_mapped} screens, {edges_mapped} edges mapped.</div>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Report written -> {out_path}")
    return out_path


if __name__ == "__main__":
    generate_report()