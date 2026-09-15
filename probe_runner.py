# -*- coding: utf-8 -*-
"""Do the sources picked in docs/P0-sources.md answer a GitHub runner the way
they answered the PC they were measured from? A 200 at home has meant a
Cloudflare 403 on the runner before (DailyNK Japan, 2026-09-14).

Access only: feed status, G2 window, G1 extraction with teaser check, G3 --
the same measure() as probe_topics.py, no model call, no key needed.
Run it on the runner and on the PC close together and compare the two files.

Controls with a known answer on both sides:
  Yonhap-NK   G1 PASS (the daily run collects it from Actions)
  38North     G1 PASS from home, article pages 403 on a runner (first run here)
  NK News     teaser
  DailyNK-JP  FEED_HTTP 403 on a runner, 200 from home

Writes probe_runner.<where>.json, where = runner when GITHUB_ACTIONS is set,
else local. Exits 1 when a control does not come out as known.
"""
import json, math, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from probe_topics import CANDIDATES, CONTROLS, NOW, measure

sys.stdout.reconfigure(errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ON_RUNNER = os.environ.get("GITHUB_ACTIONS") == "true"

PICKED = [  # docs/P0-sources.md 4절·6절 채택·보류, 피드 본문 후보 둘
    "연합 마켓", "뉴시스 국제", "서울경제 국제", "CNBC Economy", "NPR Economy", "Guardian Economics", "Fed 전체",
    "SCMP Business", "SCMP China Economy", "CNBC World", "중국신문망 재경", "CGTN Business",
    "SCMP China", "동아 국제", "The Diplomat", "Sinocism",
    "ABC International", "CBS World", "PBS NewsHour World", "NPR World", "BBC World", "Guardian World",
    "Independent World", "Fox News World", "Foreign Policy", "War on the Rocks",
    "CGTN World", "CGTN China", "CGTN Politics", "중국신문망 국제", "중국신문망 요문",
    "조선비즈 국제", "Axios",
]
EXTRA_CONTROLS = [("대조", "DailyNK-JP", "ja", "https://dailynk.jp/feed")]


def expected(name, row):
    """None when the control came out as known, else what went wrong."""
    g1 = row.get("g1") or {}
    passed = g1.get("n") and g1["pass"] >= math.ceil(g1["n"] * 0.6)
    if name == "Yonhap-NK" and not passed:
        return f"G1 {g1.get('pass')}/{g1.get('n')} (PASS 예상)"
    # 2026-09-15 runner: the 38North feed answers, every article page is a
    # Cloudflare challenge (cf-mitigated: challenge) with or without our UA.
    # Scheduled runs never met it: the deep slot picked AsiaPress each time.
    if name == "38North":
        verdicts = set(g1.get("verdicts") or [])
        if ON_RUNNER and verdicts != {"FETCH_HTTP"}:
            return f"G1 {g1.get('verdicts')} (러너에서는 전부 FETCH_HTTP 403 예상)"
        if not ON_RUNNER and not passed:
            return f"G1 {g1.get('pass')}/{g1.get('n')} (PASS 예상)"
    if name == "NK News" and g1.get("teaser") is not True:
        return f"teaser={g1.get('teaser')} (True 예상)"
    if name == "DailyNK-JP":
        want = ("FEED_HTTP", "403") if ON_RUNNER else ("OK", None)
        got = (row["feed"], row.get("why"))
        if got[0] != want[0] or (want[1] and got[1] != want[1]):
            return f"{got} ({want} 예상)"
    return None


if __name__ == "__main__":
    t0 = time.time()
    by_name = {s[1]: s for s in CANDIDATES}
    missing = [n for n in PICKED if n not in by_name]
    if missing:                                 # a renamed source would silently drop out
        raise SystemExit(f"probe_topics.CANDIDATES에 없는 이름: {missing}")
    specs = CONTROLS + EXTRA_CONTROLS + [by_name[n] for n in PICKED]

    hosts = {}
    for s in specs:
        hosts.setdefault(urlsplit(s[3]).netloc, []).append(s)
    with ThreadPoolExecutor(8) as pool:
        groups = list(pool.map(lambda g: [measure(*s)[0] for s in g], hosts.values()))
    done = {r["name"]: r for g in groups for r in g}
    rows = [done[s[1]] for s in specs]

    problems = []
    print(f"{'소스':<22}{'피드':<11}{'G1':>5}{'티저':>7}  {'G3':<10}{'최신h':>7}  메모")
    for r in rows:
        g1, g2 = r.get("g1") or {}, r.get("g2") or {}
        why = r.get("why") or ""
        if g1:
            fails = sorted({a.get("why") or a["verdict"] for a in g1["articles"] if a["verdict"] not in ("PASS", "SHORT")})
            why = ", ".join(str(f) for f in fails)
        print(f"{r['name']:<22}{r['feed']:<11}{str(g1.get('pass', '-')):>3}/{g1.get('n', '-')}"
              f"{str(g1.get('teaser', '-')):>7}  {(r.get('g3') or {}).get('verdict', '-'):<10}"
              f"{str(g2.get('newest_h', '-')):>7}  {why}")
        if r["group"] == "대조":
            p = expected(r["name"], r)
            if p:
                problems.append(f"대조 {r['name']}: {p}")

    where = "runner" if ON_RUNNER else "local"
    out = os.path.join(HERE, f"probe_runner.{where}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"measured_at": NOW.isoformat(), "where": where,
                   "runner": {k: os.environ.get(k) for k in ("RUNNER_OS", "GITHUB_RUN_ID", "GITHUB_SHA")} if ON_RUNNER else None,
                   "problems": problems, "rows": rows, "elapsed_s": round(time.time() - t0, 1)},
                  fh, ensure_ascii=False, indent=1)
    print(f"\n-> {os.path.basename(out)} ({time.time() - t0:.0f}s)")
    for p in problems:
        print("!!", p)
    if problems:
        sys.exit(1)
