# -*- coding: utf-8 -*-
"""Run the whole graph with the model and the network swapped out.

No key, no network. Checks the shape, not the judgement:
  1. normal day: source cap, cross-label duplicate re-check and refill,
     short body excluded, failed check dropped, tier1 first
  2. empty day still reaches publish
  3. dry run never writes the ledger; DRY_RUN=true stays dry
  4. a real send writes shipped items plus their dropped same-event twins
  5. every feed dead: the reader gets a failure notice, not "no articles"
  6. one worker raising does not sink the others
  7. a daily feed whose newest item is older than 24h is SILENT even though
     it still has items inside the 168h fetch
"""
import os, sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

os.environ["DRY_RUN"] = "1"
os.environ.pop("DISCORD_WEBHOOK_URL", None)
import graph

sys.stdout.reconfigure(errors="replace")
now = datetime.now(timezone.utc)

def item(src, n, hours_ago):
    return {"source": src, "title": f"{src} 기사 {n}", "link": f"https://ex.com/{src}/{n}",
            "at": (now - timedelta(hours=hours_ago)).isoformat(), "summary": ""}

FEED = ([item("Yonhap-NK", i, 2 + i) for i in range(6)]
        + [item("DailyNK", i, 3 + i) for i in range(2)]
        + [item("38North", 0, 50)])
TIER1 = {"status": "OPEN", "day": "20260914",
         "item": {"source": "통일부", "slot": "tier1", "title": "북한 동향", "url": "https://nkinfo/x?trendMngNo=1",
                  "link": "https://nkinfo/x?trendMngNo=1", "at": now.astimezone(graph.KST).isoformat(),
                  "body": "가" * 400}}
LEN = {"Yonhap-NK": 900, "DailyNK": 1500, "38North": 250}
DUPE_CALLS, WROTE = [], []

def fake_parse(system, user, schema):
    if schema is graph.Shortlist:
        lines = user.splitlines()
        # every line picked in order; lines 1 and 2 share an event label
        return schema(picks=[graph.Pick(index=i, reason="가짜", event="사건A" if i in (1, 2) else f"사건{i}")
                             for i in range(len(lines))])
    if schema is graph.Dupes:
        # first check only: short-list items 0 and 1 are the same event under different labels
        DUPE_CALLS.append(1)
        return schema(groups=[[0, 1]] if len(DUPE_CALLS) == 1 else [])
    if schema is graph.Draft:
        return graph.Draft(headline="헤드라인", summary="요약입니다.", why="중요합니다.", topic="군사·핵")
    if schema is graph.Verdict:
        # the check only sees body/headline/summary; DailyNK is the 1500-char body
        return graph.Verdict(ok="나" * 1500 not in user, problems=["가짜 불합격"])
    raise AssertionError(schema)

graph.parse = fake_parse
graph.load_ledger = lambda: {}
graph.mark_published = lambda items: WROTE.append([i["link"] for i in items])
graph.METRICS = os.devnull
graph.load_seen = lambda: {}

def run_with(feed, dead=(), tier1=TIER1, body=None):
    DUPE_CALLS.clear()
    graph.collect_feeds = lambda state: {"items": feed, "dead": [{"source": d, "reason": "x"} for d in dead],
                                         "silent": [], "gaps": [], "skips": {}, "seen_now": {},
                                         "hours": state["hours"]}
    graph.fetch_tier1 = lambda led: tier1
    graph.extract_body = body or (lambda it: it.get("body") or "나" * LEN[it["source"]])
    return graph.build().compile().invoke(graph.INIT)

def show(out):
    for line in out["log"]:
        print(line)

print("== 1. normal day ==")
out = run_with(FEED)
show(out)
assert sum(1 for a in out["picked"] if a["source"] == "Yonhap-NK") <= graph.MAX_PER_SOURCE
assert any("같은 사건 (묶음 재확인)" in l for l in out["log"]), "cross-label duplicate not dropped"
assert len([a for a in out["picked"] if a["slot"] == "breaking"]) == graph.TARGET, "slot not refilled"
assert any("제외 38North" in l for l in out["log"]), "short body not excluded"
assert all(a["source"] != "DailyNK" for a in out["verified"]), "failed check kept"
assert out["verified"][0]["slot"] == "tier1"
assert out["meta"]["twins"] and out["meta"]["twins"][0]["twin"].endswith("Yonhap-NK/0")

print("\n== 2. empty day ==")
out = run_with([], tier1={"status": "NO_PUBLICATION"})
show(out)
assert out["log"][-1].startswith("⑤ 발행"), "empty day did not reach publish"
assert not out["meta"]["failed"]

print("\n== 3. dry run ==")
os.environ["DRY_RUN"] = "true"
assert graph.is_dry(), "DRY_RUN=true must stay dry"
os.environ["DRY_RUN"] = "1"
assert WROTE == [], WROTE
print("ledger untouched, DRY_RUN=true is dry")

print("\n== 4. real send ==")
os.environ["DRY_RUN"] = "0"
os.environ["DISCORD_WEBHOOK_URL"] = "https://example.invalid/hook"
posted = []
graph.requests.post = lambda url, json, timeout: posted.append(json) or NS(status_code=204, text="")
out = run_with(FEED)
os.environ["DRY_RUN"] = "1"
del os.environ["DISCORD_WEBHOOK_URL"]
assert len(posted) == 1 and WROTE, "nothing sent or ledger not written"
links = WROTE[-1]
assert "https://ex.com/Yonhap-NK/1" in links, "same-event twin not suppressed with its sent pair"
assert all("DailyNK" not in l for l in links), "unsent (failed check) item written to ledger"
print(f"sent 1 payload, ledger +{len(links)} links (incl. suppressed twin)")

print("\n== 5. every feed dead ==")
out = run_with([], dead=[n for n, _u, _e in graph.SOURCES], tier1={"status": "DEAD", "reason": "x"})
show(out)
assert out["meta"]["failed"], "all-dead day not flagged"

print("\n== 6. one worker raises ==")
def flaky(it):
    if it["source"] == "DailyNK":
        raise ValueError("layout changed")
    return it.get("body") or "나" * LEN[it["source"]]
out = run_with(FEED, body=flaky)
assert any("원문 받기 실패 ValueError" in l for l in out["log"])
assert any(a["source"] == "Yonhap-NK" for a in out["verified"]), "other workers lost"
print("DailyNK failure logged, others published")

print("\n== 7. frozen daily feed ==")
stale = [item("Yonhap-NK", i, 2 + i) for i in range(6)] + [item("DailyNK", i, 30 + i) for i in range(2)]
out = run_with(stale)
assert "DailyNK" in out["meta"]["silent"], out["meta"]["silent"]
assert "Yonhap-NK" not in out["meta"]["silent"]
print("DailyNK SILENT over 24h while its items sit inside 168h")

print("\n== 8. twenty cards (course step 10) ==")
os.environ["DRY_RUN"] = "0"
os.environ["DISCORD_WEBHOOK_URL"] = "https://example.invalid/hook"
posted.clear(); WROTE.clear()
many = [{**item("Yonhap-NK", i, 1), "url": f"https://ex.com/Yonhap-NK/{i}", "slot": "breaking",
         "headline": f"헤드라인 {i}", "summary": "가" * 700, "why": "나" * 100, "topic": "군사·핵"}
        for i in range(20)]
res = graph.publish({"verified": many, "picked": many, "drafted": many, "meta": {"window_h": 24}})
os.environ["DRY_RUN"] = "1"
del os.environ["DISCORD_WEBHOOK_URL"]
embeds = posted[-1]["embeds"]
size = sum(len(e.get("title", "")) + len(e.get("description", "")) + len(e.get("footer", {}).get("text", ""))
           for e in embeds)
for line in res["log"]:
    print(line)
print(f"embeds {len(embeds)} · text {size} chars · ledger +{len(WROTE[-1])}")
assert len(embeds) <= graph.EMBED_MAX and size <= graph.TOTAL_MAX
assert any("[한도]" in l for l in res["log"]), "drop not logged"
assert WROTE[-1] == [a["link"] for a in many[:len(embeds) - 1]], "ledger must hold only the cards that went out"

print("\nALL OK")
