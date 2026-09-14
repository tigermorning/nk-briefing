"""G1 measures length, and a paywall that serves a generous teaser clears it.
Two signals separate a teaser from a body, and neither is length itself:

  spread  -- real articles vary in length; a teaser is cut to a fixed size
  cut     -- a teaser stops mid-sentence, so its prose does not end in . ? !

Neither is sufficient alone. The first version of this script checked `cut`
against the raw extract and flagged Yonhap and RFA 5/5, because those outlets
end with an email, an editor byline or a copyright line -- none of which ends
in punctuation. A heuristic has to be run against known-good sources before
it is trusted, or it just renames every source "suspicious".
"""
import feedparser, requests, sys
from trafilatura import extract
from test_g1 import UA

sys.stdout.reconfigure(errors="replace")

N = 5
SOURCES = [
    ("NKNews", "https://www.nknews.org/feed/"),
    ("38North", "https://www.38north.org/feed/"),
    ("Yonhap-NK", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("DailyNK", "https://www.dailynk.com/feed"),
    ("RFA-KO", "https://www.rfa.org/korean/rss2.xml"),
]

ENDERS = ".?!。\"”’'"
TAIL_MARKS = ["©", "(c)", "(C)", "All rights reserved",
              "저작권자", "무단 전재",
              "제보는", "에디터 "]

def prose_end(text):
    """Drop the trailing boilerplate so the check sees where the prose stops."""
    for mark in TAIL_MARKS:
        i = text.find(mark)
        if i > 0:
            text = text[:i]
    lines = text.split("\n")
    while lines and (not lines[-1].strip() or "@" in lines[-1]
                     or len(lines[-1].strip()) < 25):
        lines.pop()
    return "\n".join(lines).rstrip(" |\n\t")

if __name__ == "__main__":
    hdr = f"{'source':<11}{'n':>3}{'min':>7}{'max':>7}{'spread':>8}{'cut/n':>7}  note"
    print(hdr)
    print("-" * len(hdr))
    for name, url in SOURCES:
        f = feedparser.parse(requests.get(url, headers=UA, timeout=20).content)
        lens, cut = [], 0
        for e in f.entries[:N]:
            try:
                r = requests.get(e.get("link", ""), headers=UA, timeout=20)
                t = (extract(r.text) or "").strip()
            except Exception:
                continue
            if not t:
                continue
            lens.append(len(t))
            prose = prose_end(t)
            if prose and prose[-1] not in ENDERS:
                cut += 1
        if not lens:
            print(f"{name:<11}{0:>3}{'-':>7}{'-':>7}{'-':>8}{'-':>7}  nothing extracted")
            continue
        spread = max(lens) / min(lens)
        flags = []
        if spread < 1.5:
            flags.append("uniform length")
        if cut >= len(lens) - 1:
            flags.append("stops mid-sentence")
        note = " + ".join(flags) if len(flags) == 2 else (flags[0] if flags else "full text")
        verdict = "TEASER" if len(flags) == 2 else ""
        print(f"{name:<11}{len(lens):>3}{min(lens):>7}{max(lens):>7}{spread:>7.1f}x"
              f"{cut:>4}/{len(lens)}  {note} {verdict}")

    print("\nspread = longest / shortest.  cut = extracts whose prose ends mid-sentence.")
    print("TEASER = both at once. Either one alone is a normal outlet habit.")
