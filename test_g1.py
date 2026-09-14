import feedparser, requests, re, json, os, time
from datetime import datetime, timezone
from trafilatura import extract

# metrics live next to this script, not next to whatever directory you happen
# to run from -- a cwd-relative path silently starts a second, empty store
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store")
METRICS = os.path.join(STORE, "metrics.jsonl")

BASE = 600
UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
SOURCES = [
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("DailyNK", "https://www.dailynk.com/feed"),
    ("38North", "https://www.38north.org/feed/"),
    ("RFA-KO", "https://www.rfa.org/korean/rss2.xml"),
]

def judge(link):
    """Return (verdict, ext_len, http_code).

    Four verdicts, not two. PASS/FAIL alone cannot tell 'this article is a
    2-line stub' apart from 'we never got the page' -- and those need
    opposite responses: drop the source vs fix our own request.
    """
    try:
        r = requests.get(link, headers=UA, timeout=20)
    except Exception as exc:
        return f"FETCH_ERR({type(exc).__name__})", 0, -1
    if r.status_code != 200:
        return "FETCH_HTTP", 0, r.status_code
    ext = extract(r.text) or ""
    if not ext:
        # 200 but nothing came out -- our extractor's problem, not the source's
        return "EXTRACT_EMPTY", 0, r.status_code
    if len(ext) < BASE:
        return "SHORT", len(ext), r.status_code
    return "PASS", len(ext), r.status_code

def rss_body(e):
    body = e.get("content", [{}])[0].get("value") if e.get("content") else e.get("summary", "")
    return re.sub(r"<[^>]+>", "", body or "").strip()

t0 = time.time()
rows, tally = [], {}
hdr = f"{'source':<10}{'rss_len':>8}{'ext_len':>9}{'code':>6}  {'verdict':<22}title"
print(hdr)
print("-" * 95)
for name, url in SOURCES:
    try:
        f = feedparser.parse(requests.get(url, headers=UA, timeout=20).content)
    except Exception as exc:
        print(f"{name:<10}{'-':>8}{'-':>9}{'-':>6}  {'FEED_ERR':<22}{type(exc).__name__}")
        tally.setdefault(name, {})["FEED_ERR"] = 1
        continue
    if not f.entries:
        # a 200 with an empty feed is a failure that looks like success
        print(f"{name:<10}{'-':>8}{'-':>9}{'-':>6}  {'FEED_EMPTY':<22}")
        tally.setdefault(name, {})["FEED_EMPTY"] = 1
        continue
    for e in f.entries[:3]:
        verdict, ext_len, code = judge(e.get("link", ""))
        rl = len(rss_body(e))
        print(f"{name:<10}{rl:>8}{ext_len:>9}{code:>6}  {verdict:<22}{e.get('title','')[:35]}")
        rows.append((name, rl, ext_len, verdict))
        d = tally.setdefault(name, {})
        d[verdict] = d.get(verdict, 0) + 1

print()
print("verdict tally by source:")
for name, d in tally.items():
    print(f"  {name:<10}{d}")

# a source whose RSS is long but whose extraction is empty is OUR bug, not theirs
suspect = [n for n, rl, el, v in rows if v == "EXTRACT_EMPTY" and rl >= BASE]
if suspect:
    print()
    print("!! EXTRACT_EMPTY while RSS carries full text -> our extractor, not the source:",
          sorted(set(suspect)))

n_pass = sum(1 for *_, v in rows if v == "PASS")
os.makedirs(STORE, exist_ok=True)
with open(METRICS, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                         "g1_base": BASE, "g1_tally": tally,
                         "g1_pass_rate": round(n_pass / len(rows), 3) if rows else None,
                         "g1_extractor_suspect": sorted(set(suspect)),
                         "elapsed_s": round(time.time() - t0, 1)},
                        ensure_ascii=False) + "\n")
print(f"\n{n_pass}/{len(rows)} PASS (>= {BASE}) -> store/metrics.jsonl append done")
