import feedparser, requests, json, os, time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# metrics live next to this script, not next to whatever directory you happen
# to run from -- a cwd-relative path silently starts a second, empty store
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store")
SEEN = os.path.join(STORE, "last_seen.json")
METRICS = os.path.join(STORE, "metrics.jsonl")

UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
# expect_daily: sources that should produce something in a normal 24h window.
# 38North publishes weekly, so a 0 from it is news; a 0 from Yonhap is alarm.
SOURCES = [
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml", True),
    ("DailyNK", "https://www.dailynk.com/feed", True),
    ("38North", "https://www.38north.org/feed/", False),
    ("RFA-KO", "https://www.rfa.org/korean/rss2.xml", False),
    # added 2026-09-14 from probe_sources.py: of 21 foreign candidates these
    # two brought events the Korean feeds did not carry (DailyNK Japan: 3 of
    # 4 in 72h) or reporting nobody else does (AsiaPress price surveys).
    # DailyNK Japan runs ~2 a day, so a 0 day is not an alarm.
    ("DailyNK-JP", "https://dailynk.jp/feed", False),
    ("AsiaPress", "https://www.asiapress.org/apn/feed/index.xml", False),
]

# Feeds that are not North Korea only. An entry is kept only if its title or
# summary names the North in the feed's language -- AsiaPress also runs
# Japanese domestic pieces (5 of 16 when measured). /apn/feed/ without
# index.xml answers 200 with a one-line meta-refresh page and 0 entries.
NK_KEYWORDS = {
    "DailyNK-JP": ["北朝鮮", "金正恩", "平壌", "朝鮮民主主義"],
    "AsiaPress": ["北朝鮮", "金正恩", "平壌", "朝鮮民主主義"],
}

def link_key(link):
    """Identity of an article link. Strip only tracking tags: the query is
    often the article id itself (nkinfo view.do?...&trendMngNo=134739), and
    cutting at '?' makes every article of such a site the same key."""
    parts = urlsplit(link or "")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))

def load_seen():
    try:
        with open(SEEN, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

def collect(state):
    hours = state.get("hours", 24)
    # A short feed can drop articles between two runs and leave no trace: the
    # count just looks like a slow day. If the oldest entry we can still see is
    # NEWER than the newest we saw last time, everything in between fell out.
    seen_before = load_seen()
    seen_now, gaps = {}, []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items, seen, dead = [], set(), []
    # skipped items are NOT logged one by one -- that would bury the real signal.
    # counts only: bounded size, still lets you explain a drop in the total.
    skips = {}

    for name, url, _expect in SOURCES:
        s = skips.setdefault(name, {"nodate": 0, "old": 0, "dup": 0, "offtopic": 0, "kept": 0})
        try:
            r = requests.get(url, headers=UA, timeout=20)
            if r.status_code != 200:
                raise ValueError(f"http {r.status_code}")
            f = feedparser.parse(r.content)
            # a 200 with no entries ends the loop silently and never raises.
            # make it loud, or a dead feed reads as a quiet news day forever.
            if not f.entries:
                raise ValueError("empty feed")
        except Exception as exc:
            # reason, not just the name -- otherwise every recovery starts by
            # reproducing the failure to find out what it even was
            dead.append({"source": name, "reason": f"{type(exc).__name__}: {exc}"})
            continue

        times = sorted(datetime(*t[:6], tzinfo=timezone.utc) for t in
                       (e.get("published_parsed") or e.get("updated_parsed")
                        for e in f.entries) if t)
        if times:
            seen_now[name] = times[-1].isoformat()
            prev = seen_before.get(name)
            if prev and times[0] > datetime.fromisoformat(prev):
                gaps.append({"source": name, "last_seen": prev,
                             "oldest_now": times[0].isoformat()})

        for e in f.entries:
            t = e.get("published_parsed")
            if not t:
                s["nodate"] += 1
                continue
            at = datetime(*t[:6], tzinfo=timezone.utc)
            if at < cutoff:
                s["old"] += 1
                continue
            kws = NK_KEYWORDS.get(name)
            if kws and not any(k in e.get("title", "") + e.get("summary", "") for k in kws):
                s["offtopic"] += 1
                continue
            key = link_key(e.get("link", ""))
            if key in seen:
                s["dup"] += 1
                continue
            seen.add(key)
            s["kept"] += 1
            # at/summary feed the later stages: publish prints the time, and
            # report compares extracted length against what the feed already gave
            items.append({"source": name, "title": e.get("title", ""),
                          "link": e.get("link", ""), "at": at.isoformat(),
                          "summary": e.get("summary", "") or ""})

    # a source that answered fine and still gave nothing: not an error, but the
    # one shape of trouble that leaves no other trace at all
    dead_names = {d["source"] for d in dead}
    silent = [n for n, _u, expect in SOURCES
              if expect and n not in dead_names and skips[n]["kept"] == 0]

    return {"items": items, "dead": dead, "silent": silent, "gaps": gaps,
            "skips": skips, "seen_now": seen_now, "hours": hours}

if __name__ == "__main__":
    import sys
    t0 = time.time()
    res = collect({"hours": int(sys.argv[1]) if len(sys.argv) > 1 else 24})
    by_src = {}
    for it in res["items"]:
        by_src[it["source"]] = by_src.get(it["source"], 0) + 1

    print(f"hours={res['hours']}  total={len(res['items'])}  by_src={by_src}")
    print(f"{'source':<11}{'kept':>6}{'old':>6}{'dup':>6}{'off':>6}{'nodate':>8}")
    for name, s in res["skips"].items():
        print(f"{name:<11}{s['kept']:>6}{s['old']:>6}{s['dup']:>6}{s['offtopic']:>6}{s['nodate']:>8}")
    for d in res["dead"]:
        print(f"!! DEAD   {d['source']}: {d['reason']}")
    for n in res["silent"]:
        print(f"!! SILENT {n}: responded OK but contributed 0 in a {res['hours']}h window")
    for g in res["gaps"]:
        print(f"!! GAP    {g['source']}: feed now starts at {g['oldest_now']}, "
              f"past our last sighting {g['last_seen']} -- articles fell out unseen")
    if not res["dead"] and not res["silent"] and not res["gaps"]:
        print("all sources accounted for")

    os.makedirs(STORE, exist_ok=True)
    with open(METRICS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                             "hours": res["hours"], "collect": by_src,
                             "total": len(res["items"]),
                             "dead": res["dead"], "silent": res["silent"],
                             "gaps": res["gaps"],
                             "skips": res["skips"],
                             "elapsed_s": round(time.time() - t0, 1)},
                            ensure_ascii=False) + "\n")
    if res["seen_now"]:
        merged = load_seen()
        merged.update(res["seen_now"])
        with open(SEEN, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=1)
