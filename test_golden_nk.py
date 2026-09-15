# -*- coding: utf-8 -*-
"""The North Korea brief must come out of the P1 refactor unchanged.

P1 (docs/PLAN-email-edition.md) moves what graph.py and collect_nk.py
hard-code about North Korea -- sources, keywords, the reporter's role, the
claim warning, tier1 -- into the briefing yaml. This test pins what the code
produces from fixed fake inputs, so "unchanged" is a comparison, not a claim:

  config   every prompt the model is given and every source setting
  collect  collect_nk.collect over fake RSS for every source: which entries
           survive, which carry a feed body, the skip counts
  runs     graph.run() with the model, network and ledger faked, on a normal
           day (tier1, a 403 page answered by the feed body, a Japanese
           source, a rewrite), an every-feed-dead day and an empty day: every
           model call (schema, system, user), the Discord payload, the log,
           the metrics row and the ledger writes

Dates and times are normalised. Report workers run in parallel and finish in
any order, so model calls and log lines are compared as sorted lists; the
payload keeps its order.

  python test_golden_nk.py           compare with golden/nk_p1.json
  python test_golden_nk.py --write   write it -- only from code known to be right

No key, no network. Nothing in the repository is written without --write.
"""
import json, os, pathlib, re, sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace as NS

os.environ["DRY_RUN"] = "1"
for k in ("DISCORD_WEBHOOK_URL", "NK_SKIP_SOURCES"):
    os.environ.pop(k, None)
import collect_nk
import graph

sys.stdout.reconfigure(errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
GOLDEN = HERE / "golden" / "nk_p1.json"
NOW = datetime.now(timezone.utc)

DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[+-]\d{2}:\d{2}|Z)?)?")
WHEN = re.compile(r"(?<![\d-])\d{2}-\d{2}(?: \d{2}:\d{2})?(?![\d-])")
STAMP = re.compile(r"[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}")

def norm(x):
    s = json.dumps(x, ensure_ascii=False, sort_keys=True)
    for pat, rep in ((STAMP, "<stamp>"), (DATE, "<date>"), (WHEN, "<when>")):
        s = pat.sub(rep, s)
    return json.loads(s)

def sorted_dumps(rows):
    return sorted(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows)


# ---------------------------------------------------------------- config
def config():
    return {
        "graph.SOURCES": graph.SOURCES, "collect_nk.SOURCES": collect_nk.SOURCES,
        "NK_KEYWORDS": collect_nk.NK_KEYWORDS, "FULL_TEXT_FEEDS": sorted(collect_nk.FULL_TEXT_FEEDS),
        "WEEKLY": sorted(graph.WEEKLY), "SOURCE_LANG": graph.SOURCE_LANG, "TOPICS": graph.TOPICS,
        "CRITERIA": graph.CRITERIA, "SYS_DRAFT": graph.SYS_DRAFT, "SYS_CHECK": graph.SYS_CHECK,
        "numbers": [graph.BRIEF_SIZE, graph.BRIEF_MAX, graph.TARGET, graph.MAX_PER_SOURCE, graph.BODY_MIN,
                    graph.DEEP_WINDOW_H, graph.TIER1_LOOKBACK_D],
        "lang_head": {name: [graph.lang_head("plain body", name), graph.lang_head("한국어 본문", name)]
                      for name, _u, _e in graph.SOURCES + [("미등록", "", False)]},
    }


# ---------------------------------------------------------------- collect
def rss(entries):
    items = "".join(
        f"<item><title>{t}</title><link>{link}</link><pubDate>{format_datetime(at)}</pubDate>"
        f"<description><![CDATA[<p>{summary}</p>]]></description>"
        f"<content:encoded><![CDATA[<p>{body}</p>]]></content:encoded></item>"
        for t, link, at, summary, body in entries)
    return (f'<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            f"<channel><title>t</title>{items}</channel></rss>").encode()

def collect_snapshot():
    feeds = {}
    for k, (name, url, _e) in enumerate(collect_nk.SOURCES):
        base = f"https://ex.com/{name}"
        feeds[url] = rss([
            (f"北朝鮮 {name} 1", f"{base}/1", NOW - timedelta(hours=2 + k), "北朝鮮 요약...", "Body text. " * 80),
            (f"東京 {name} 2", f"{base}/2", NOW - timedelta(hours=3 + k), "東京 요약", "Other. " * 80),
            (f"{name} 3 옛 기사", f"{base}/3", NOW - timedelta(days=10), "old", "Old. " * 80),
        ])
    real_get, real_seen = collect_nk.requests.get, collect_nk.load_seen
    collect_nk.requests.get = lambda url, **kw: NS(status_code=200, content=feeds[url])
    collect_nk.load_seen = lambda: {}
    try:
        got = collect_nk.collect({"hours": 168})
    finally:
        collect_nk.requests.get, collect_nk.load_seen = real_get, real_seen
    return {"items": [{"source": i["source"], "title": i["title"], "link": i["link"],
                       "feed_body": i.get("feed_body")} for i in got["items"]],
            "skips": got["skips"], "dead": got["dead"], "silent": got["silent"], "off": got["off"]}


# ---------------------------------------------------------------- runs
CALLS, POSTED, WROTE, ROWS = [], [], [], []

def fake_parse(system, user, schema):
    CALLS.append({"schema": schema.__name__, "system": system, "user": user})
    if schema is graph.Shortlist:
        # every line in order; the event comes from the title so it does not
        # depend on list order, and Yonhap 1 and 2 share one
        lines = user.splitlines()
        events = [re.sub(r"^\d+\. ", "", l) for l in lines]
        return schema(picks=[graph.Pick(index=i, reason=f"이유{i}",
                                        event="사건A" if re.search(r"Yonhap-NK 기사 [12]$", e) else e)
                             for i, e in enumerate(events)])
    if schema is graph.Dupes:
        return schema(groups=[])
    marker = (re.search(r"<<([^>]+)>>", user) or re.search(r"(北朝鮮)", user) or re.search(r"(가{10})", user)).group(1)
    if schema is graph.Draft:
        fixed = "[검수에서 지적된 문제]" in user
        topics = list(graph.TOPICS)
        return graph.Draft(headline=("수정 " if fixed else "") + f"헤드라인 {marker}", summary="요약입니다.",
                           why="중요합니다.", topic=topics[len(marker) % len(topics)])
    if schema is graph.Verdict:
        # one card fails its first check and passes after the rewrite
        bad = marker == "Yonhap-NK-0" and "수정 헤드라인" not in user
        return graph.Verdict(claims=["초안 / 원문 / 유지"], ok=not bad, problems=["가짜 불합격"] if bad else [])
    raise AssertionError(schema)

def item(src, n, hours_ago, **extra):
    return {"source": src, "title": f"{src} 기사 {n}", "link": f"https://ex.com/{src}/{n}",
            "at": (NOW - timedelta(hours=hours_ago)).isoformat(), "summary": "", **extra}

NORTH_BODY = "<<38North-0>> " + "Commercial satellite imagery shows a new facility. " * 40

def body(it):
    if it.get("body"):
        return it["body"]
    if it["source"] == "38North":                # a runner's Cloudflare challenge
        resp = graph.requests.Response()
        resp.status_code = 403
        resp.headers["cf-mitigated"] = "challenge"
        raise graph.requests.HTTPError("403", response=resp)
    if it["source"] in ("AsiaPress", "DailyNK-JP"):
        return "北朝鮮の物価調査。" * 120
    return f"<<{it['link'].split('ex.com/')[1].replace('/', '-')}>> " + "나" * 900

TIER1 = {"status": "OPEN", "day": "20260914",
         "item": {"source": "통일부", "slot": "tier1", "title": "북한 동향", "url": "https://nkinfo/x?trendMngNo=1",
                  "link": "https://nkinfo/x?trendMngNo=1", "at": NOW.astimezone(graph.KST).isoformat(),
                  "body": "가" * 400}}

def run(feed, dead=(), tier1=TIER1):
    CALLS.clear(); POSTED.clear(); WROTE.clear(); ROWS.clear()
    graph.collect_feeds = lambda state: {"items": feed, "dead": [{"source": d, "reason": "x"} for d in dead],
                                         "silent": [], "gaps": [], "skips": {}, "seen_now": {},
                                         "hours": state["hours"]}
    graph.fetch_tier1 = lambda led: tier1
    out = graph.run()
    row = {k: v for k, v in ROWS[-1].items() if k not in ("ts", "elapsed_s", "log")}
    return {"calls": sorted_dumps(CALLS), "payload": json.loads(json.dumps(POSTED)), "log": sorted(out["log"]),
            "row": row, "ledger": WROTE[:]}

def runs():
    graph.parse = fake_parse
    graph.load_ledger = lambda: {}
    graph.mark_published = lambda items: WROTE.append([i["link"] for i in items])
    graph.load_seen = lambda: {}
    graph.append_row = ROWS.append
    graph.extract_body = body
    graph.requests.post = lambda url, json, timeout: POSTED.append(json) or NS(status_code=204, text="")
    os.environ["DRY_RUN"] = "0"
    os.environ["DISCORD_WEBHOOK_URL"] = "https://example.invalid/hook"
    try:
        normal = ([item("Yonhap-NK", i, 2 + i) for i in range(5)]
                  + [item("DailyNK", i, 3 + i) for i in range(2)]
                  + [item("RFA-KO", 0, 5), item("DailyNK-JP", 0, 6)]
                  + [item("38North", 0, 50, feed_body=NORTH_BODY, summary="Commercial satellite imagery shows ..."),
                     item("AsiaPress", 0, 60)])
        return {"normal": run(normal),
                "all_dead": run([], dead=[n for n, _u, _e in graph.SOURCES], tier1={"status": "DEAD", "reason": "x"}),
                "empty": run([], tier1={"status": "NO_PUBLICATION"})}
    finally:
        os.environ["DRY_RUN"] = "1"
        os.environ.pop("DISCORD_WEBHOOK_URL", None)


# ---------------------------------------------------------------- compare
def diff(a, b, path="", out=None):
    out = [] if out is None else out
    if type(a) is not type(b):
        out.append(f"{path}: type {type(a).__name__} -> {type(b).__name__}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: {'없음' if k not in a else '있음'} -> {'없음' if k not in b else '있음'}")
            else:
                diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: 길이 {len(a)} -> {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out)
    elif a != b:
        a, b = str(a), str(b)
        # long prompts differ late: show where, not the same first 160 chars twice
        i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        out.append(f"{path} @{i}: …{a[max(0, i - 40):i + 60]!r} -> …{b[max(0, i - 40):i + 60]!r}")
    return out

if __name__ == "__main__":
    snap = norm({"config": config(), "collect": collect_snapshot(), "runs": runs()})
    assert snap["runs"]["normal"]["payload"] and snap["runs"]["normal"]["ledger"], "fixture sent nothing"
    assert any("피드 본문 사용" in l for l in snap["runs"]["normal"]["log"]), "fixture missed the feed-body path"
    assert any("재작성 후 통과" in l for l in snap["runs"]["normal"]["log"]), "fixture missed the rewrite path"
    if "--write" in sys.argv:
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN.relative_to(HERE)}")
        sys.exit(0)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    problems = diff(golden, snap)
    for p in problems[:30]:
        print("DIFF", p)
    if problems:
        print(f"FAILED: {len(problems)} differences from {GOLDEN.relative_to(HERE)}")
        sys.exit(1)
    print("ALL OK: config, collect and three runs match the golden file")
