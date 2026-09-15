# -*- coding: utf-8 -*-
"""Scorecard from store/metrics.jsonl -- no new tooling, only the rows already written.

Gates ask "can we use this source"; this asks "is it any use". A source that
passed every gate and still contributes 0 for weeks is the case to look at.
"""
import json, sys
from collections import Counter
from collect_nk import METRICS, SOURCES

sys.stdout.reconfigure(errors="replace")

rows = []
try:
    with open(METRICS, encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
except FileNotFoundError:
    pass
# the file also holds collect_nk.py probe rows with a different shape
graph_rows = [r for r in rows if r.get("kind") == "graph"]
crashed = [r for r in graph_rows if r.get("error")]
runs = [r for r in graph_rows if not r.get("error")]
real = [r for r in runs if not r.get("dry_run")]

if not graph_rows:
    print("아직 그래프 실행 기록이 없습니다. python run.py 를 한 번 이상 돌리세요.")
    raise SystemExit

print(f"그래프 실행 {len(runs)}줄 (실발행 {len(real)} · dry-run {len(runs) - len(real)})"
      f" · 중간에 죽은 실행 {len(crashed)}줄\n")
pub = Counter()
for r in runs:
    pub.update(r["by_source"])
print(f"{'소스':<12}{'검수 통과 기여':>10}")
print("-" * 26)
for name in [n for n, _u, _e in SOURCES] + ["통일부"]:     # zero rows must show too
    print(f"{name:<12}{pub.get(name, 0):>10}")

print("\n최근 실행: 속보후보 → 선별 → 취재 → 검수통과  창  1차")
for r in runs[-7:]:
    flag = " ESC" if r.get("escalated") else ""
    flag += " MIN" if r.get("below_min") else ""
    print(f"  {r['run_id']}  {r['collected']:>3} → {r['picked']:>2} → {r['drafted']:>2}"
          f" → {r['published']:>2}   {r.get('window_h')}h{flag}  {r.get('tier1')}")

alerts = Counter()
for r in runs:
    for d in r.get("dead") or []:
        alerts[f"DEAD {d['source']}"] += 1
    for n in r.get("silent") or []:
        alerts[f"SILENT {n}"] += 1
    if r.get("tier1") in ("DEAD", "STALE"):
        alerts[f"{r['tier1']} 통일부"] += 1
    if r.get("failed"):
        alerts["FAILED 실패 공지 발행"] += 1
for r in crashed:
    alerts[f"CRASH {r['error'][:40]}"] += 1
if alerts:
    print("\n경보 누적:", dict(alerts))


def plot(path):
    """Stage pass rates per run (course step 12). The text table above is the
    table view; the chart only shows the trend. Labels are English because
    matplotlib's default fonts have no Hangul glyphs."""
    try:
        import matplotlib
    except ImportError:
        raise SystemExit("--plot에는 matplotlib이 필요합니다: pip install -r requirements-dev.txt")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rate = lambda a, b: (a / b) if b else None
    stages = [  # validated order (dataviz validate_palette.js, light): blue, orange, aqua
        ("select  picked / candidates", "#2a78d6", lambda r: rate(r["picked"], r["collected"] + r["deep"])),
        ("report  drafted / picked", "#eb6834", lambda r: rate(r["drafted"], r["picked"])),
        ("verify  passed / drafted", "#1baf7a", lambda r: rate(r["published"], r["drafted"])),
    ]
    xs = list(range(len(runs)))
    fig, ax = plt.subplots(figsize=(9, 4), facecolor="#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ends = {}
    # lines often sit on top of each other at 100%; dash/marker keep each one
    # visible, and end labels that land on the same value are merged
    styles = [("-", "o"), ("--", "s"), (":", "D")]
    for (label, color, f), (ls, mk) in zip(stages, styles):
        ys = [f(r) for r in runs]
        ax.plot(xs, ys, color=color, linewidth=2, linestyle=ls, marker=mk, markersize=5, label=label)
        last = next(((x, y) for x, y in zip(reversed(xs), reversed(ys)) if y is not None), None)
        if last:
            ends.setdefault((last[0], round(last[1], 2)), []).append(label.split()[0])
    for (x, y), names in ends.items():            # direct labels: aqua is under 3:1 on the surface
        ax.annotate(" · ".join(names), (x, y), xytext=(8, 0), textcoords="offset points",
                    va="center", fontsize=9, color="#52514e")
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xticks(xs, [r["run_id"][5:] for r in runs], rotation=45, ha="right", fontsize=8, color="#52514e")
    ax.tick_params(axis="y", colors="#52514e", labelsize=8)
    ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.set_title("Stage pass rate per run", loc="left", fontsize=11, color="#0b0b0b")
    ax.legend(frameon=False, fontsize=8, loc="lower left", labelcolor="#52514e")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print(f"\n-> {path}")

if "--plot" in sys.argv:
    plot(sys.argv[sys.argv.index("--plot") + 1] if len(sys.argv) > sys.argv.index("--plot") + 1 else "funnel.png")
