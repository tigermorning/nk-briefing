# -*- coding: utf-8 -*-
"""The MOU API gives a short summary plus a link to nkinfo. If the link does
not yield a body, the tier1 slot would be written from a headline -- what G1
exists to prevent.

Filtering to "only items that have a body" is the obvious fix and it works
mechanically: cn >= 300 keeps every item that later passes G1 and skips 56
fetches. It still does not close the question, for a reason the filter cannot
see. Across all 73 items ext_len - cn_len stays between 300 and 338 -- the
detail page is the same summary plus a constant slab of page furniture. The
fetch adds no text at all, so "PASS" here means cn + boilerplate cleared 600,
not that a body exists. Filtering picks the longest summaries; it cannot
produce an article that the source never published.
"""
import io, sys, requests
from urllib.robotparser import RobotFileParser
from test_g1 import judge, UA, BASE
from mou_api import get_trend

sys.stdout.reconfigure(errors="replace")

CN_MIN = 300   # pre-fetch filter: only chase items whose summary is already substantial

def check_robots(base):
    """Return (verdict, RobotFileParser or None).

    A non-200 must never be parsed. An error page parses as 'no rules found',
    which reads as 'everything allowed' -- the same mistake RobotFileParser
    makes on its own when a site 403s its default User-Agent.
    """
    try:
        r = requests.get(base + "/robots.txt", headers=UA, timeout=20)
    except Exception as exc:
        return f"UNKNOWN ({type(exc).__name__})", None
    if r.status_code in (404, 400, 410):
        # no robots.txt published -- the standard reading is 'not disallowed'
        return f"ABSENT (http {r.status_code}) -> allowed", None
    if r.status_code != 200:
        return f"UNKNOWN (http {r.status_code})", None
    if "<html" in r.text[:200].lower():
        return "UNKNOWN (html, not robots.txt)", None
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return "PARSED", rp

if __name__ == "__main__":
    verdict, rp = check_robots("https://nkinfo.unikorea.go.kr")
    print(f"G3 nkinfo robots.txt: {verdict}\n")

    res = get_trend("daily", 30, rows=100)
    items = res.get("items", []) or []
    print(f"items in 30 days: {len(items)}  (totalCount={res.get('totalCount')})\n")

    kept = [i for i in items if len(i.get("cn") or "") >= CN_MIN]
    print(f"pre-filter cn >= {CN_MIN}: {len(kept)}/{len(items)} items\n")

    hdr = f"{'cn_len':>7}{'ext_len':>9}{'code':>6}  {'G3':<7}{'verdict':<10}title"
    print(hdr)
    print("-" * 80)
    tally, report = {}, []
    for it in items:
        url = it.get("url") or ""
        g3 = "allowed" if rp is None else ("OK" if rp.can_fetch("*", url) else "BLOCK")
        v, ext_len, code = judge(url)
        tally[v] = tally.get(v, 0) + 1
        it["_ext"] = ext_len
        it["_v"] = v
        if len(it.get("cn") or "") >= CN_MIN or v == "PASS":
            print(f"{len(it.get('cn') or ''):>7}{ext_len:>9}{code:>6}  {g3:<7}{v:<10}{(it.get('sj') or '')[:26]}")
        report.append(f"{it.get('first_reg_ymd')}\tcn={len(it.get('cn') or '')}\text={ext_len}\t{v}\t{it.get('sj')}")

    # A fetch that only ever adds a constant is not fetching a body. Compare
    # the gain, not the absolute length, or boilerplate alone can clear G1.
    gains = [i["_ext"] - len(i.get("cn") or "") for i in items if i["_ext"]]
    if gains:
        lo, hi = min(gains), max(gains)
        print(f"\next_len - cn_len: min {lo}  max {hi}  mean {sum(gains)/len(gains):.0f}")
        if hi - lo < 100:
            print("!! NO_GAIN -- the page adds a constant, not an article body. "
                  "G1 PASS here is the summary plus page furniture")

    print(f"\nverdict over all {len(items)}: {tally}")
    passed = [i for i in items if i["_v"] == "PASS"]
    pf = [i for i in kept if i["_v"] == "PASS"]
    print(f"G1 PASS: {len(passed)}/{len(items)} overall")
    print(f"         {len(pf)}/{len(kept)} among the cn>={CN_MIN} pre-filtered")
    if kept:
        print(f"pre-filter precision = {len(pf)}/{len(kept)}, and it skips "
              f"{len(items)-len(kept)} fetches")
    days = sorted({i.get("first_reg_ymd") for i in passed})
    print(f"days with a usable item: {len(days)} of 30 -> {days}")
    io.open("mou_g1_report.txt", "w", encoding="utf-8").write("\n".join(report))
    print("-> mou_g1_report.txt")
