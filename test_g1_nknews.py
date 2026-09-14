"""NK News sits behind a paywall, so G1's job here is to say WHICH failure it
is. SHORT means the site served us a teaser and the source cannot fill a
briefing slot. EXTRACT_EMPTY or a FETCH_* means our own request is wrong and
the source has not been judged yet."""
import feedparser, requests, sys
from test_g1 import judge, rss_body, UA, BASE

sys.stdout.reconfigure(errors="replace")
URL = "https://www.nknews.org/feed/"
N = 5

f = feedparser.parse(requests.get(URL, headers=UA, timeout=20).content)
print(f"entries={len(f.entries)}  checking first {N}\n")

hdr = f"{'rss_len':>8}{'ext_len':>9}{'code':>6}  {'verdict':<16}title"
print(hdr)
print("-" * 78)
verdicts = {}
for e in f.entries[:N]:
    verdict, ext_len, code = judge(e.get("link", ""))
    v = verdict.split("(")[0]
    verdicts[v] = verdicts.get(v, 0) + 1
    print(f"{len(rss_body(e)):>8}{ext_len:>9}{code:>6}  {verdict:<16}{e.get('title','')[:34]}")

print(f"\ntally: {verdicts}   (G1 base = {BASE} chars)")
if verdicts.get("SHORT"):
    print("SHORT -> the site itself gave us a teaser. paywall confirmed, source unusable for slots")
if verdicts.get("EXTRACT_EMPTY"):
    print("EXTRACT_EMPTY -> 200 but nothing extracted: our extractor, not the paywall. not yet judged")
if [k for k in verdicts if k.startswith("FETCH")]:
    print("FETCH_* -> we never got the page. fix the request before judging the source")
