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
