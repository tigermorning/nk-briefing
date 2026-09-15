import feedparser, requests, json, os, re, time
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import briefing_cfg

# metrics live next to this script, not next to whatever directory you happen
# to run from -- a cwd-relative path silently starts a second, empty store
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store")
SEEN = os.path.join(STORE, "last_seen.json")
METRICS = os.path.join(STORE, "metrics.jsonl")

UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
# Which feeds to read comes from the briefing yaml's 소스 (audience.yaml for
# North Korea; the why of each source is written next to it there). One
# process runs one briefing, so these module names are set once at start-up
# and read at call time by collect, active_sources and graph:
#   SOURCES          (name, feed url, expect_daily) in collection order.
#                    expect_daily: a 0 in 24h is an alarm (Yonhap), not news (38North)
#   NK_KEYWORDS      name -> words; an entry is kept only when its title or
#                    summary contains one (feeds that are not about the briefing only)
#   FULL_TEXT_FEEDS  names whose content:encoded is the whole article, kept as
#                    plain text so report can fall back to it when the page is
#                    blocked (38North on a runner, 2026-09-15)
def configure(cfg):
    global SOURCES, NK_KEYWORDS, FULL_TEXT_FEEDS
    SOURCES = [(s["이름"], s["주소"], s["매일기대"]) for s in cfg["소스"]]
    NK_KEYWORDS = {s["이름"]: list(s["키워드"]) for s in cfg["소스"] if s["키워드"]}
    FULL_TEXT_FEEDS = {s["이름"] for s in cfg["소스"] if s["피드본문"]}

configure(briefing_cfg.load())

_BLOCK = {"p", "div", "br", "hr", "li", "ul", "ol", "dl", "dt", "dd", "pre",
          "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "figure", "figcaption",
          "table", "caption", "tr", "section", "article", "aside"}
_CELL = {"td", "th"}                            # 2024 | 5,000, not "20245,000"
# the footer is its own paragraph, so its own line: anchored to a line start, an
# article whose last sentence opens "The post of ambassador..." keeps it
_FOOTER = re.compile(r"(?:^|\n)The post [^\n]{1,400} appeared first on [^\n]{1,80}\Z")

class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in _BLOCK:
            self.out.append("\n")
        elif tag in _CELL:
            self.out.append(" | ")
    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK:
            self.out.append("\n")
    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)

def html_text(html):
    """Plain text of an HTML fragment, one line per block, footer removed."""
    p = _Text()
    p.feed(html or "")
    p.close()
    lines = (re.sub(r"[ \t\r\f\v\xa0]+", " ", l).strip().strip(" |") for l in "".join(p.out).split("\n"))
    return _FOOTER.sub("", "\n".join(l for l in lines if l)).strip()

def feed_text(e):
    """content:encoded as plain text, or "" when the entry has none or the
    HTML cannot be read -- report then refuses it and collect logs NOFEED,
    instead of one odd entry stopping every source's collection."""
    try:
        for c in e.get("content") or []:
            if "html" in (c.get("type") or "html") and c.get("value"):
                return html_text(c["value"])
    except Exception:
        return ""
    return ""


RETRY_WAIT_S = 3

def get_once_more(url, **kw):
    """requests.get with one retry on a connection error or timeout.

    Measured 2026-09-15 on an Actions dry run: Yonhap reset one connection and
    data.go.kr timed out once, each marking its source DEAD for the day; the
    same runner reached both at once on the next tries (3 of 3). An HTTP error
    status is an answer, not a network blip, and is not retried."""
    try:
        return requests.get(url, **kw)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        time.sleep(RETRY_WAIT_S)
        return requests.get(url, **kw)

def active_sources():
    """SOURCES minus the names in NK_SKIP_SOURCES (comma-separated).

    DailyNK Japan answers 200 from home and a Cloudflare 403 challenge from a
    GitHub runner whatever the headers (measured 2026-09-14), so Actions turns
    it off rather than logging the same DEAD every morning -- a daily alarm
    that is always on hides the day a real feed dies. A name that matches no
    source raises: a typo would otherwise switch nothing off and say nothing."""
    off = {n.strip() for n in os.environ.get("NK_SKIP_SOURCES", "").split(",") if n.strip()}
    unknown = off - {n for n, _u, _e in SOURCES}
    if unknown:
        raise ValueError(f"NK_SKIP_SOURCES names no such source: {sorted(unknown)}")
    return [s for s in SOURCES if s[0] not in off], sorted(off)

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
    sources, off = active_sources()

    for name, url, _expect in sources:
        s = skips.setdefault(name, {"nodate": 0, "old": 0, "dup": 0, "offtopic": 0, "kept": 0})
        try:
            r = get_once_more(url, headers=UA, timeout=20)
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
            it = {"source": name, "title": e.get("title", ""),
                  "link": e.get("link", ""), "at": at.isoformat(),
                  "summary": e.get("summary", "") or ""}
            if name in FULL_TEXT_FEEDS:
                it["feed_body"] = feed_text(e)
            items.append(it)

    # a source that answered fine and still gave nothing: not an error, but the
    # one shape of trouble that leaves no other trace at all
    dead_names = {d["source"] for d in dead}
    silent = [n for n, _u, expect in sources
              if expect and n not in dead_names and skips[n]["kept"] == 0]

    return {"items": items, "dead": dead, "silent": silent, "gaps": gaps,
            "skips": skips, "seen_now": seen_now, "hours": hours, "off": off}

if __name__ == "__main__":
    import sys
    t0 = time.time()
    res = collect({"hours": int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 24})
    by_src = {}
    for it in res["items"]:
        by_src[it["source"]] = by_src.get(it["source"], 0) + 1

    print(f"hours={res['hours']}  total={len(res['items'])}  by_src={by_src}")
    print(f"{'source':<11}{'kept':>6}{'old':>6}{'dup':>6}{'off':>6}{'nodate':>8}")
    for name, s in res["skips"].items():
        print(f"{name:<11}{s['kept']:>6}{s['old']:>6}{s['dup']:>6}{s['offtopic']:>6}{s['nodate']:>8}")
    for n in res["off"]:
        print(f"-- OFF    {n}: switched off by NK_SKIP_SOURCES")
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
                             "dead": res["dead"], "silent": res["silent"], "off": res["off"],
                             "gaps": res["gaps"],
                             "skips": res["skips"],
                             "elapsed_s": round(time.time() - t0, 1)},
                            ensure_ascii=False) + "\n")
    # store/last_seen.json is the GAP baseline the scheduled run relies on. A
    # hand-run collect moving it forward would hide a gap from tomorrow's run,
    # so only an explicit --save-seen writes it (peer review 2026-09-15)
    if res["seen_now"] and "--save-seen" in sys.argv:
        merged = load_seen()
        merged.update(res["seen_now"])
        with open(SEEN, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=1)
