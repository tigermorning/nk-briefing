import feedparser, requests, json, os, time
from datetime import datetime, timezone

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store")
METRICS = os.path.join(STORE, "metrics.jsonl")

UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
DAILY_MIN, WEEKLY_MIN = 7, 1
SOURCES = [
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("DailyNK", "https://www.dailynk.com/feed"),
    ("38North", "https://www.38north.org/feed/"),
    ("RFA-KO", "https://www.rfa.org/korean/rss2.xml"),
    ("NKNews", "https://www.nknews.org/feed/"),
    ("Chinanews", "https://www.chinanews.com.cn/rss/world.xml"),
    ("Yonhap-JP", "https://jp.yna.co.kr/RSS/nk.xml"),
    ("DailyNK-EN", "https://www.dailynk.com/english/rss-feed/"),
]

def when(e):
    """Return (datetime, which_field). feedparser fills published_parsed only
    when the feed uses a field it recognises as 'published'. A feed that dates
    its items with <updated> or <dc:date> leaves it None -- and a date we did
    not look for is not the same thing as an item with no date."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        t = e.get(field)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc), field
    return None, None

if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    t0 = time.time()
    out = {"ts": now.isoformat(), "g2": {}}

    hdr = f"{'source':<12}{'entries':>8}{'14d':>6}{'nodate':>8}{'other_field':>13}  {'daily':<7}{'weekly':<7}"
    print(hdr)
    print("-" * len(hdr))
    for name, url in SOURCES:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            if r.status_code != 200:
                raise ValueError(f"http {r.status_code}")
            f = feedparser.parse(r.content)
            if not f.entries:
                raise ValueError("empty feed")
        except Exception as exc:
            print(f"{name:<12}{'-':>8}{'-':>6}{'-':>8}{'-':>13}  DEAD: {type(exc).__name__}: {exc}")
            out["g2"][name] = {"dead": f"{type(exc).__name__}: {exc}"}
            continue

        in14, nodate, fields = 0, 0, {}
        for e in f.entries:
            dt, field = when(e)
            if dt is None:
                nodate += 1
                continue
            fields[field] = fields.get(field, 0) + 1
            if (now - dt).total_seconds() / 86400 <= 14:
                in14 += 1

        # items dated by a field other than published_parsed: the old code would
        # have counted every one of these as nodate and dropped them
        other = sum(n for fld, n in fields.items() if fld != "published_parsed")
        d = "PASS" if in14 >= DAILY_MIN else "-"
        w = "PASS" if in14 >= WEEKLY_MIN else "-"
        print(f"{name:<12}{len(f.entries):>8}{in14:>6}{nodate:>8}{other:>13}  {d:<7}{w:<7}")
        out["g2"][name] = {"entries": len(f.entries), "in14": in14, "nodate": nodate,
                           "date_fields": fields, "daily": d == "PASS", "weekly": w == "PASS"}

    print(f"\nthresholds: daily 14d>={DAILY_MIN}, weekly 14d>={WEEKLY_MIN}")
    suspect = [n for n, v in out["g2"].items()
               if "dead" not in v and v["nodate"] > 0]
    if suspect:
        print("!! nodate > 0 -- those items are dropped by the time window with no other trace:", suspect)

    out["elapsed_s"] = round(time.time() - t0, 1)
    os.makedirs(STORE, exist_ok=True)
    with open(METRICS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(out, ensure_ascii=False) + "\n")
    print("-> store/metrics.jsonl append done")
