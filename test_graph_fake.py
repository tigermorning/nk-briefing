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
  8. twenty cards: embeds trimmed to Discord's limits, ledger holds only what went out
  9. 44 candidates: prelim splits into equal batches (no 40 + 4 tail)
  10. a draft still not Korean after the retry is dropped
  11. forward/reversed ranking merge
  12. a source switched off by NK_SKIP_SOURCES is logged, a typo stops the
      run, and every remaining feed dead still raises the failure notice
  13. 3 cards a day (4 only with both deep and tier1), breaking by select
      rank, not the order the workers finished in
  14. a tenfold figure the model judge passes is caught by the number check,
      the rewrite sees the finding, and the fixed card ships
  15. a card still wrong after its one rewrite is dropped, the spare takes
      the slot, and the judge is shown the why line too
  16. every feed dead but tier1 open: the card goes out with a warning, the
      ledger is written, and the fallback run counts the day as sent
  17. the judge call fails for every card: the reader gets a failure notice,
      not "no articles today", and the fallback run retries
  18. the webhook times out after the request went out: counted as sent, so
      the ledger is written and the fallback run does not post it again
  19. a feed request that hits one connection error is retried once; an HTTP
      error status is not retried
  20. a 38North article page answering a Cloudflare 403: the full-text feed
      body stands in, the log and metrics say so, a teaser feed body is refused
  21. another briefing yaml: its sources, keywords, feed body, prompts and
      title are used, tier1 is never fetched without 1차칸, and North Korea
      comes back after
  22. the run stops midway (no model credit, 2026-09-17): the reader gets a
      notice naming the cause, once a day, never after a posted brief or in a
      dry run, and the fallback still retries the brief
"""
import os, re, sys
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
        return graph.Verdict(claims=[], ok="나" * 1500 not in user, problems=["가짜 불합격"])
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
brief = graph.BRIEF_SIZE, graph.BRIEF_MAX
graph.BRIEF_SIZE = graph.BRIEF_MAX = 20        # the Discord limits, not the daily card count, are under test
res = graph.publish({"verified": many, "picked": many, "drafted": many, "meta": {"window_h": 24}})
graph.BRIEF_SIZE, graph.BRIEF_MAX = brief
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

print("\n== 9. 44 candidates: equal prelim batches ==")
CALL_SIZES = []
real_parse = graph.parse
def sizing_parse(system, user, schema):
    if schema is graph.Shortlist:
        CALL_SIZES.append((len(user.splitlines()), int(re.search(r"최대 (\d+)건", system).group(1))))
    return real_parse(system, user, schema)
graph.parse = sizing_parse
big = [item("Yonhap-NK" if k % 3 else "DailyNK", k, 1 + k % 20) for k in range(44)]
out = run_with(big, tier1={"status": "NO_PUBLICATION"})
graph.parse = real_parse
prelim = CALL_SIZES[:2]
print("prelim calls (lines, keep):", prelim, "· log:", [l for l in out["log"] if "예선" in l])
assert prelim == [(22, 4), (22, 4)], prelim     # not 40 + 4 with the tail batch keeping everything

print("\n== 10. draft still not Korean after the retry ==")
real_draft = graph.draft
graph.draft = lambda body, source="": (graph.Draft(headline="北朝鮮", summary="要約", why="重要", topic="군사·핵"), 1)
out = run_with(FEED[:6], tier1={"status": "NO_PUBLICATION"})
graph.draft = real_draft
assert not out["drafted"] and any("한글 없는 칸" in l for l in out["log"]), out["log"]
print("excluded:", [l.strip() for l in out["log"] if "한글 없는 칸" in l][0])

print("\n== 11. forward/reversed merge ==")
items12 = [item("DailyNK", k, 1) for k in range(6)]
def order_biased(system, user, schema):
    lines = user.splitlines()                   # a model that always prefers whatever is listed first
    return schema(picks=[graph.Pick(index=i, reason="", event=f"e{lines[i]}") for i in range(3)])
graph.parse = order_biased
merged = [p.index for p in graph.ranked_both_ways(items12, 3)]
graph.parse = real_parse
print("forward picks 0,1,2 · reversed picks 5,4,3 → merged", merged)
assert merged == [0, 5, 1, 4, 2, 3], merged      # neither end of the list wins outright

print("\n== 12. source switched off (NK_SKIP_SOURCES) ==")
import collect_nk
os.environ["NK_SKIP_SOURCES"] = "DailyNK-JP, AsiaPress"
active, off = collect_nk.active_sources()
assert off == ["AsiaPress", "DailyNK-JP"] and all(n not in off for n, _u, _e in active), (active, off)
os.environ["NK_SKIP_SOURCES"] = "DailyNK-JPN"
try:
    collect_nk.active_sources()
    raise AssertionError("typo in NK_SKIP_SOURCES accepted")
except ValueError as exc:
    print("typo stops the run:", exc)
del os.environ["NK_SKIP_SOURCES"]
rest = [n for n, _u, _e in graph.SOURCES if n != "DailyNK-JP"]
graph.collect_feeds = lambda state: {"items": [], "dead": [{"source": d, "reason": "x"} for d in rest],
                                     "silent": [], "gaps": [], "skips": {}, "seen_now": {},
                                     "hours": state["hours"], "off": ["DailyNK-JP"]}
graph.fetch_tier1 = lambda led: {"status": "DEAD", "reason": "x"}
out = graph.build().compile().invoke(graph.INIT)
show(out)
assert any("OFF    DailyNK-JP" in l for l in out["log"]), "switched-off source not logged"
assert out["meta"]["failed"], "every remaining feed dead must still raise the failure notice"

print("\n== 13. card count ==")
def card(slot, rank=0):
    return {"slot": slot, "rank": rank, "source": slot, "headline": f"{slot}{rank}"}
brk = [card("breaking", r) for r in (3, 0, 2, 1)]                 # workers finish out of order
for extra, want in (([], ["breaking0", "breaking1", "breaking2"]),
                    ([card("deep")], ["breaking0", "breaking1", "deep0"]),
                    ([card("tier1")], ["tier10", "breaking0", "breaking1"]),
                    ([card("tier1"), card("deep")], ["tier10", "breaking0", "breaking1", "deep0"])):
    ver, spare = graph.fit_brief(brk + extra)
    got = [a["headline"] for a in ver]
    print(f"{len(extra)} special -> {got} · spare {len(spare)}")
    assert got == want, got

print("\n== 14. number check catches what the judge passes, rewrite fixes it ==")
MONEY = "북한이 벌어들인 수입은 100억달러로 추정된다. " + "나" * 900
JUDGE_SAW = []
def lenient(system, user, schema):
    if schema is graph.Verdict:                 # passes everything, like 100억 -> 1,000억 on 2026-09-15
        JUDGE_SAW.append(user)
        return graph.Verdict(claims=[], ok=True, problems=[])
    if schema is graph.Draft:
        fixed = "원문에 없는 숫자 '1,000억'" in user and "[BAD]" not in user
        money = "100억" if fixed else "1,000억"
        return graph.Draft(headline="북한 수입 추정", summary=f"수입은 약 {money} 달러로 추정됩니다.",
                           why="대러 협력의 규모를 보여 주기 때문에 중요합니다.", topic="대외·외교")
    return fake_parse(system, user, schema)
graph.parse = lenient
out = run_with(FEED[:3], tier1={"status": "NO_PUBLICATION"}, body=lambda it: MONEY)
graph.parse = real_parse
show(out)
n = len(out["drafted"])
assert n >= 2 and out["meta"]["check"] == {"first_fail": n, "rewritten": n, "dropped": 0}, out["meta"]["check"]
assert all("100억" in a["summary"] and "1,000억" not in a["summary"] for a in out["verified"]), "inflated figure kept"
assert any("원문에 없는 숫자 '1,000억'" in l for l in out["log"]) and any("재작성 후 통과" in l for l in out["log"])
assert JUDGE_SAW and all("[왜 중요한지]" in u for u in JUDGE_SAW), "judge did not see the why line"

print("\n== 15. still wrong after the rewrite: dropped, spare fills ==")
def body15(it):
    if it["source"] == "38North":
        return "나" * 250
    return MONEY + (" [BAD]" if it["link"].endswith("Yonhap-NK/0") else "")
graph.parse = lenient
out = run_with(FEED, tier1={"status": "NO_PUBLICATION"}, body=body15)
graph.parse = real_parse
show(out)
assert out["meta"]["check"]["dropped"] == 1, out["meta"]["check"]
assert all(not a["link"].endswith("Yonhap-NK/0") for a in out["verified"]), "card wrong after rewrite was kept"
assert any("재작성 후에도" in l for l in out["log"])
assert out["meta"]["shipped"] == graph.BRIEF_SIZE, "spare did not take the dropped card's slot"

print("\n== 16. every feed dead, tier1 open: card goes out once ==")
import run as runmod
os.environ["DRY_RUN"] = "0"
os.environ["DISCORD_WEBHOOK_URL"] = "https://example.invalid/hook"
posted = []
graph.requests.post = lambda url, json, timeout: posted.append(json) or NS(status_code=204, text="")
WROTE.clear()
out = run_with([], dead=[n for n, _u, _e in graph.SOURCES], tier1=TIER1)
os.environ["DRY_RUN"] = "1"
del os.environ["DISCORD_WEBHOOK_URL"]
show(out)
meta = out["meta"]
assert meta["failed"] and meta["shipped"] == 1 and meta["sent"] is True, meta
lead = posted[-1]["embeds"][0]["description"]
assert "⚠️" in lead and "모든 뉴스 피드 수집에 실패해" in lead, lead
assert len(posted[-1]["embeds"]) == 2 and "[1차]" in posted[-1]["embeds"][1]["title"]
assert WROTE and WROTE[-1] == [TIER1["item"]["link"]], WROTE
row = {"kind": "graph", "run_id": "2026-09-16 07:30", "dry_run": False,
       "failed": meta["failed"], "shipped": meta["shipped"], "sent": meta["sent"]}
assert runmod.sent_today([row], "2026-09-16") == "2026-09-16 07:30", "fallback would send the tier1 card again"
print("tier1 card sent with a warning, ledger written, fallback sees the day as sent")

print("\n== 17. judge call fails for every card: failure notice, fallback retries ==")
def judge_down(system, user, schema):
    if schema is graph.Verdict:
        raise RuntimeError("429 from the model")
    return fake_parse(system, user, schema)
graph.parse = judge_down
out = run_with(FEED[:6], tier1={"status": "NO_PUBLICATION"})
graph.parse = real_parse
show(out)
meta = out["meta"]
assert out["drafted"] and not out["verified"], "fixture should draft and then lose every card in verify"
assert "검수를 통과하지 못해" in meta["failed"], meta["failed"]
assert meta["shipped"] == 0
row = {"kind": "graph", "run_id": "2026-09-16 07:30", "dry_run": False,
       "failed": meta["failed"], "shipped": meta["shipped"], "sent": True}
assert runmod.sent_today([row], "2026-09-16") == "", "fallback must retry after a verify outage"
print("failure notice instead of a quiet day, fallback retries")

print("\n== 18. webhook read timeout: may have posted, ledger written, counts as sent ==")
os.environ["DRY_RUN"] = "0"
os.environ["DISCORD_WEBHOOK_URL"] = "https://example.invalid/hook"
def slow_post(url, json, timeout):
    raise graph.requests.exceptions.ReadTimeout("no answer in time")
graph.requests.post = slow_post
WROTE.clear()
out = run_with(FEED, tier1={"status": "NO_PUBLICATION"})
os.environ["DRY_RUN"] = "1"
del os.environ["DISCORD_WEBHOOK_URL"]
meta = out["meta"]
assert meta["sent"] == "unknown" and meta["shipped"] >= 1, meta
assert WROTE, "a possibly posted brief must reach the ledger"
assert any("보냈을 수 있음" in l for l in out["log"])
row = {"kind": "graph", "run_id": "2026-09-16 07:30", "dry_run": False,
       "failed": meta["failed"], "shipped": meta["shipped"], "sent": meta["sent"]}
assert runmod.sent_today([row], "2026-09-16") == "2026-09-16 07:30"
print("read timeout recorded as maybe-sent, ledger written, fallback skips")

print("\n== 19. one network blip is retried once, an HTTP error is not ==")
import collect_nk
calls = []
def flaky_get(url, **kw):
    calls.append(url)
    if len(calls) == 1:
        raise collect_nk.requests.exceptions.ConnectionError("connection reset by peer")
    return NS(status_code=200, content=b"ok")
real_get, real_wait = collect_nk.requests.get, collect_nk.RETRY_WAIT_S
collect_nk.requests.get, collect_nk.RETRY_WAIT_S = flaky_get, 0
assert collect_nk.get_once_more("https://ex.com/feed").status_code == 200 and len(calls) == 2
calls.clear()
collect_nk.requests.get = lambda url, **kw: calls.append(url) or NS(status_code=503, content=b"")
assert collect_nk.get_once_more("https://ex.com/feed").status_code == 503 and len(calls) == 1
collect_nk.requests.get = lambda url, **kw: (_ for _ in ()).throw(collect_nk.requests.exceptions.ConnectTimeout("x"))
try:
    collect_nk.get_once_more("https://ex.com/feed")
    raise AssertionError("a second failure must still raise")
except collect_nk.requests.exceptions.ConnectTimeout:
    pass
collect_nk.requests.get, collect_nk.RETRY_WAIT_S = real_get, real_wait
print("retried once on a connection error, not on 503, raises after the second failure")

print("\n== 20. article page 403 (Cloudflare challenge): full-text feed body stands in, and says so ==")
# collect keeps content:encoded as plain text, only for FULL_TEXT_FEEDS
pub = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
ARTICLE = ("<p>Commercial satellite imagery shows Sinuiju&#8217;s new customs area.</p>"
           + "<p>" + "Trucks wait at the gate. " * 60 + "</p>"
           + "<table><tr><td>2024</td><td>5,000</td></tr></table>"
           # a last paragraph that opens like the WordPress footer must survive
           + "<p>The post of ambassador in Pyongyang remains vacant.</p>")
FOOTER = '<p>The post <a href="https://www.38north.org/x/">X</a> appeared first on <a href="https://www.38north.org">38 North</a>.</p>'
RSS = f"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>t</title>
<item><title>North Korea X</title><link>https://www.38north.org/x/</link><pubDate>{pub}</pubDate>
<description><![CDATA[<p>Commercial satellite imagery shows ...</p>{FOOTER}]]></description>
<content:encoded><![CDATA[{ARTICLE}{FOOTER}]]></content:encoded></item></channel></rss>""".encode()
os.environ["NK_SKIP_SOURCES"] = ",".join(n for n, _u, _e in collect_nk.SOURCES if n not in ("38North", "DailyNK"))
collect_nk.requests.get = lambda url, **kw: NS(status_code=200, content=RSS if "38north" in url else
                                               RSS.replace(b"38north.org/x/</link>", b"ex.com/dnk/</link>"))
got = collect_nk.collect({"hours": 24})
collect_nk.requests.get = real_get
del os.environ["NK_SKIP_SOURCES"]
by = {i["source"]: i for i in got["items"]}
fb = by["38North"]["feed_body"]
assert "feed_body" not in by["DailyNK"], "a feed not opted in must not carry feed_body"
assert fb.startswith("Commercial satellite imagery shows Sinuiju’s"), fb[:60]
assert fb.endswith("gate.\n2024 | 5,000\nThe post of ambassador in Pyongyang remains vacant."), fb[-80:]
assert "appeared first on" not in fb and "<p>" not in fb, "footer or tags left in the feed body"
assert collect_nk.html_text(by["38North"]["summary"]).endswith("..."), "excerpt fixture should end in ..."
print(f"collect: 38North feed_body {len(fb)} chars, footer and tags gone; DailyNK carries none")

def challenged(it):
    resp = graph.requests.Response()
    resp.status_code = 403
    resp.headers["cf-mitigated"] = "challenge"
    raise graph.requests.HTTPError("403 Client Error", response=resp)
def http_error(status, **headers):
    def fail(it):
        resp = graph.requests.Response()
        resp.status_code = status
        resp.headers.update(headers)
        raise graph.requests.HTTPError(f"{status} Client Error", response=resp)
    return fail
north = dict(item("38North", 0, 50), feed_body=fb, summary=by["38North"]["summary"])
ROWS = []
real_append = graph.append_row
graph.append_row = ROWS.append
run_with([], tier1={"status": "NO_PUBLICATION"}, body=challenged)   # sets the fakes; graph.run() below does the real pass
graph.collect_feeds = lambda state: {"items": [item("DailyNK", 0, 3), north], "dead": [], "silent": [], "gaps": [],
                                     "skips": {}, "seen_now": {}, "hours": state["hours"]}
out = graph.run()
graph.append_row = real_append
show(out)
deep = [a for a in out["drafted"] if a["source"] == "38North"]
assert deep and deep[0]["body_via"] == "feed" and deep[0]["body"] == fb[:6000], "feed body not used after 403"
assert "feed_body" not in deep[0], "the feed copy should not ride along after it became the body"
assert any("38North" in l and "피드 본문 사용 (페이지 HTTPError 403 cf-challenge)" in l for l in out["log"]), out["log"]
assert any("제외 DailyNK · 원문 받기 실패 HTTPError" in l for l in out["log"]), "a feed without full text still fails as before"
assert ROWS[-1]["body_via"] == {"feed": 1}, ROWS[-1]["body_via"]
assert not any("NOFEED" in l for l in out["log"]), "a good full-text feed must not raise NOFEED"

# the page answers but extracts short: the feed stands in through report too, and says why
graph.extract_body = lambda it: "short" * 20
res = graph.report({"item": dict(north, slot="deep")})
assert res["drafted"] and res["drafted"][0]["body_via"] == "feed", res
assert f"피드 본문 사용 (페이지 추출 100자 < {graph.BODY_MIN} 앞부분 'shortshort" in res["log"][0], res["log"]
# page fine: page wins, and the log names it for a full-text source
graph.extract_body = lambda it: "p" * 900
res = graph.report({"item": dict(north, slot="deep")})
assert res["drafted"][0]["body_via"] == "page" and "· 원문 페이지" in res["log"][0], res["log"]
# a connection error after the retry: the feed stands in, the log names the error type
graph.extract_body = lambda it: (_ for _ in ()).throw(graph.requests.exceptions.ConnectionError("reset"))
assert graph.get_body(north, graph.BODY_MIN)[1:] == ("feed", "페이지 ConnectionError")
# 404: the article is gone, not blocked -- the feed's copy must not be published
graph.extract_body = http_error(404)
try:
    graph.get_body(north, graph.BODY_MIN)
    raise AssertionError("a 404 page was replaced by the feed body")
except graph.requests.HTTPError:
    pass
res = graph.report({"item": dict(north, slot="deep")})
assert not res["drafted"] and "원문 받기 실패 HTTPError 404" in res["log"][0], res["log"]
# opted in but the entry had no content:encoded: refused, both reasons, counted
graph.extract_body = challenged
res = graph.report({"item": dict(north, slot="deep", feed_body="")})
assert res["body_refused"] == ["38North"] and "페이지 HTTPError 403 cf-challenge · 피드 본문 없음" in res["log"][0], res
# a response-like object that is not a requests Response must not crash the worker
assert graph.page_failure(type("E", (Exception,), {"response": object()})()) == "E"

# excerpt shapes: WordPress [...] and "Continue reading <title>", and a marker-less
# excerpt barely longer than the summary; a quote ending in an ellipsis is an article
body = "Trucks wait at the gate. " * 30
for text, bad in ((body + "[…]", True), (body + "Continue reading North Korea X", True),
                  (body + "... Read the full article", True), (body.strip(), False),
                  (body + "“We will wait…”", False)):
    got_problem = graph.feed_body_problem(text, graph.BODY_MIN)
    assert bool(got_problem) == bad, (text[-40:], got_problem)
excerpt = "<p>" + "Trucks wait at the gate. " * 20 + "...</p>"          # 500-char excerpt as the summary
assert "3배 미만" in graph.feed_body_problem(body.strip(), graph.BODY_MIN, excerpt)
assert graph.feed_body_problem(fb, graph.BODY_MIN, by["38North"]["summary"]) == ""

# the feed turns into excerpts: no teaser reaches the model, both reasons are logged and counted
teaser = dict(north, feed_body=collect_nk.html_text("<p>" + "Trucks wait at the gate. " * 30 + "[&#8230;]</p>" + FOOTER))
graph.collect_feeds = lambda state: {"items": [teaser], "dead": [], "silent": [], "gaps": [],
                                     "skips": {}, "seen_now": {}, "hours": state["hours"]}
graph.extract_body = challenged
graph.append_row = ROWS.append
out = graph.run()
graph.append_row = real_append
show(out)
assert not out["drafted"], "a teaser feed body was drafted"
assert any("원문 받기 실패 페이지 HTTPError 403 cf-challenge · 피드 본문이 발췌문 끝맺음" in l for l in out["log"]), out["log"]
assert any("NOFEED 38North" in l for l in out["log"]), "excerpt-only full-text feed not flagged at collect"
assert ROWS[-1]["body_via"] == {"refused": 1}, ROWS[-1]["body_via"]
print("403 -> feed body used and logged, metrics body_via {'feed': 1}; short page and connection error -> feed;"
      " 404 -> no feed; teaser and empty feed body refused and counted")

print("\n== 21. another briefing yaml: its sources, prompts and title, no tier1 ==")
import tempfile, pathlib, briefing_cfg
OTHER = """제목: "시험 브리핑"
기자역할: "시험 국제 브리핑 기자"
주장_주의: "원문이 정부 발표로 전하는 내용을 사실처럼 단정"
1차칸: null
독자: {누구: "시험 독자", 이미_아는_것: "기본 구도"}
중요도_기준: ["실제로 일어난 일인가"]
버릴_것: []
토픽: [{이름: "외교", 데스크지침: "주체를 밝힐 것"}]
소스:
  - {이름: "WireA", 주소: "https://a.example/feed", 칸: 속보, 매일기대: true}
  - {이름: "WeeklyB", 주소: "https://b.example/feed", 칸: 심층, 매일기대: false, 언어: "영어", 키워드: ["China"], 피드본문: true}
"""
with tempfile.TemporaryDirectory() as d:
    path = pathlib.Path(d) / "시험.yaml"
    path.write_text(OTHER, encoding="utf-8")
    other = graph.load_cfg(path)
nk_sources = graph.SOURCES
saved = {k: getattr(graph, k) for k in ("fetch_tier1", "extract_body", "collect_feeds")}
saved_post, saved_seen = graph.requests.post, collect_nk.load_seen
graph.configure(other)
try:
    assert graph.SOURCES == collect_nk.SOURCES == [("WireA", "https://a.example/feed", True),
                                                   ("WeeklyB", "https://b.example/feed", False)], graph.SOURCES
    assert graph.WEEKLY == {"WeeklyB"} and graph.SOURCE_LANG == {"WeeklyB": "영어"}
    assert collect_nk.NK_KEYWORDS == {"WeeklyB": ["China"]} and collect_nk.FULL_TEXT_FEEDS == {"WeeklyB"}
    assert graph.SYS_DRAFT.startswith("당신은 시험 국제 브리핑 기자입니다. 독자는 시험 독자입니다.")
    assert "- 원문이 정부 발표로 전하는 내용을 사실처럼 단정\n" in graph.SYS_CHECK
    assert "북한" not in graph.SYS_DRAFT + graph.SYS_CHECK + graph.CRITERIA, "North Korea left in another briefing's prompts"
    assert "- 외교: 주체를 밝힐 것" in graph.SYS_DRAFT

    # collect reads the new sources: keyword filter and feed body follow the yaml
    B = RSS.replace(b"<title>North Korea X</title>", b"<title>China and US talks</title>")
    OFF = RSS.replace(b"<title>North Korea X</title>", b"<title>Local weather</title>").replace(
        b"38north.org/x/</link>", b"b.example/off/</link>").replace(b"Commercial satellite imagery shows ...", b"weather")
    A = RSS.replace(b"38north.org/x/</link>", b"a.example/1/</link>")
    feeds = {"https://a.example/feed": A, "https://b.example/feed": B.replace(b"</channel>", OFF[OFF.index(b"<item>"):OFF.index(b"</channel>")] + b"</channel>")}
    collect_nk.requests.get = lambda url, **kw: NS(status_code=200, content=feeds[url])
    collect_nk.load_seen = lambda: {}
    got = collect_nk.collect({"hours": 24})
    by = {i["source"]: i for i in got["items"]}
    assert set(by) == {"WireA", "WeeklyB"} and got["skips"]["WeeklyB"]["offtopic"] == 1, got["skips"]
    assert by["WeeklyB"]["feed_body"] and "feed_body" not in by["WireA"]

    # the run: no tier1 call at all, the deep slot from 심층, the title from the yaml
    def no_tier1(led):
        raise AssertionError("tier1 fetched for a briefing without 1차칸")
    os.environ["DRY_RUN"] = "0"
    os.environ["DISCORD_WEBHOOK_URL"] = "https://example.invalid/hook"
    posted = []
    graph.requests.post = lambda url, json, timeout: posted.append(json) or NS(status_code=204, text="")
    graph.collect_feeds = lambda state: {"items": [item("WireA", i, 2 + i) for i in range(3)] + [item("WeeklyB", 0, 30)],
                                         "dead": [], "silent": [], "gaps": [], "skips": {}, "seen_now": {},
                                         "hours": state["hours"]}
    graph.fetch_tier1 = no_tier1
    graph.extract_body = lambda it: "나" * 900
    out = graph.build().compile().invoke(graph.INIT)
    show(out)
    assert out["tier1"] == {"status": "NOT_CONFIGURED"} and any("1차 NOT_CONFIGURED" in l for l in out["log"])
    assert any(a["slot"] == "deep" and a["source"] == "WeeklyB" for a in out["picked"]), out["picked"]
    assert posted and posted[-1]["username"] == "시험 브리핑" and posted[-1]["embeds"][0]["title"].endswith("· 시험 브리핑")
finally:
    # everything this scenario swapped, so a scenario after it starts clean
    graph.configure(graph.load_cfg())
    for k, v in saved.items():
        setattr(graph, k, v)
    graph.requests.post, collect_nk.load_seen, collect_nk.requests.get = saved_post, saved_seen, real_get
    os.environ["DRY_RUN"] = "1"
    os.environ.pop("DISCORD_WEBHOOK_URL", None)
assert graph.SOURCES == nk_sources and "북한 뉴스 브리핑 기자" in graph.SYS_DRAFT, "North Korea not restored"
print("another yaml: its sources, keywords, feed body, prompts and title; tier1 never called; North Korea restored")

print("\n== 22. the run stops midway (no model credit): the reader is told, once a day ==")
import json, httpx, openai
def no_credit(system, user, schema):
    body = {"message": "You have no credits remaining. https://platform.openai.com/settings/organization/billing/",
            "type": "insufficient_quota", "param": None, "code": "credit_balance_exhausted"}
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    raise openai.RateLimitError("Error code: 429 https://platform.openai.com/x",
                                response=httpx.Response(429, request=req, json={"error": body}), body=body)
tmp_metrics = pathlib.Path(tempfile.mkdtemp()) / "metrics.jsonl"
saved22 = {k: getattr(graph, k) for k in ("METRICS", "append_row", "parse", "mark_published")}
graph.METRICS, graph.append_row = str(tmp_metrics), real_append
os.environ["DRY_RUN"] = "0"
os.environ["DISCORD_WEBHOOK_URL"] = "https://example.invalid/hook"
posted = []
graph.requests.post = lambda url, json, timeout: posted.append(json) or NS(status_code=204, text="")
def crashed_run():
    try:
        graph.run()
    except openai.RateLimitError:
        return [json.loads(l) for l in tmp_metrics.read_text(encoding="utf-8").splitlines()][-1]
    raise AssertionError("the crash must still raise, so Actions goes red")
try:
    graph.parse = no_credit                                  # the crash comes in select, after collect
    graph.fetch_tier1 = lambda led: {"status": "NO_PUBLICATION"}
    graph.extract_body = lambda it: "나" * LEN[it["source"]]
    graph.collect_feeds = lambda state: {"items": FEED, "dead": [], "silent": [], "gaps": [], "skips": {},
                                         "seen_now": {}, "hours": state["hours"]}
    row = crashed_run()
    text = posted[-1]["embeds"][0]["description"]
    assert len(posted) == 1 and text == "⚠️ 모델 사용 크레딧이 떨어져 오늘 브리핑을 만들지 못했습니다.", posted
    assert "http" not in json.dumps(posted[-1]), "the exception message leaked into the notice"
    assert row["error"] == "RateLimitError" and row["notice"] is True, row
    assert runmod.sent_today([row], row["run_id"][:10]) == "", "a crash notice must not count as today's brief"
    # the fallback run crashes the same way: brief retried, notice not repeated
    row = crashed_run()
    assert len(posted) == 1 and row["notice"] is False, (len(posted), row)
    # a crash after the brief went out: no "no brief today" notice on top of it
    tmp_metrics.write_text("", encoding="utf-8")
    posted.clear()
    graph.parse = real_parse
    def ledger_broken(items):
        raise OSError("disk full")
    graph.mark_published = ledger_broken
    try:
        graph.run()
        raise AssertionError("ledger failure should raise")
    except OSError:
        pass
    assert len(posted) == 1 and "⚠️" not in json.dumps(posted[0], ensure_ascii=False), "notice sent after the brief"
    assert json.loads(tmp_metrics.read_text(encoding="utf-8").splitlines()[-1])["notice"] is False
    # a dry run only prints the notice
    tmp_metrics.write_text("", encoding="utf-8")
    posted.clear()
    os.environ["DRY_RUN"] = "1"
    graph.parse = no_credit
    graph.mark_published = saved22["mark_published"]
    row = crashed_run()
    assert not posted and row["notice"] is False and row["dry_run"] is True, row
    # reasons by type and code only
    class APIConnectionError(Exception): pass
    class RateLimitError(Exception):
        code, type = "rate_limit_exceeded", "requests"
    assert graph.crash_reason(APIConnectionError("https://secret")) == "모델 서버에 연결하지 못해"
    assert graph.crash_reason(RateLimitError()) == "모델 호출 한도에 걸려"
    assert graph.crash_reason(KeyError("x")) == "실행 중 오류(KeyError)가 나"
finally:
    for k, v in saved22.items():
        setattr(graph, k, v)
    os.environ["DRY_RUN"] = "1"
    os.environ.pop("DISCORD_WEBHOOK_URL", None)
print("credit exhausted: notice posted once and names the cause without the message; fallback retries the brief"
      " without a second notice; no notice after a posted brief or in a dry run")

print("\nALL OK")
