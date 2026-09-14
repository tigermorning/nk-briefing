# -*- coding: utf-8 -*-
"""Course step 7 on North Korea articles.

  A  batch size: the same 72h pool split into batches of 10, 20 and 40,
     each batch keeping a fifth (2 / 4 / 8), then one final top 5 over the
     survivors -- with the pipeline's own ask_picks (structured output).
     Batch 40 runs twice, so run-to-run noise is measured next to the
     batch-size effect instead of being mistaken for it.
  B  format: the section-6 way (plain "numbers, comma separated", parsed
     with int()) repeated 20 times at temperature 0 and 20 at 0.7.
"""
import re
from collections import Counter
from common import CRITERIA, chat, load, save, pmap, short
import graph

P = load("pool.json")
N = len(P)
print(f"pool {N}건 · " + ", ".join(f"{s} {c}" for s, c in Counter(p["source"] for p in P).items()))

# ---------------------------------------------------------------- A
def prelim(size):
    batches = [list(range(k, min(k + size, N))) for k in range(0, N, size)]
    keep = max(1, size // 5)
    def one(batch):
        picks = graph.ask_picks([P[i] for i in batch], keep)
        return [batch[p.index] for p in picks][:keep]
    survivors = [i for got in pmap(one, batches) for i in got]
    final = graph.ask_picks([P[i] for i in survivors], 5)
    return {"batches": [len(b) for b in batches], "keep": keep, "survivors": survivors,
            "final": [survivors[p.index] for p in final][:5]}

runs = {}
for name, size in (("10", 10), ("20", 20), ("40", 40), ("40 again", 40)):
    runs[name] = prelim(size)
    r = runs[name]
    print(f"\n== 묶음 {name}: 묶음 {r['batches']} · 묶음당 {r['keep']}건 → 통과 {len(r['survivors'])}건")
    print("  최종 5:")
    for i in r["final"]:
        print(f"    {i:>2} [{P[i]['source']:<10}] {short(P[i]['title'], 44)}")
    print("  통과자 소스:", dict(Counter(P[i]["source"] for i in r["survivors"])))

print("\n== 겹침")
names = list(runs)
for a in range(len(names)):
    for b in range(a + 1, len(names)):
        x, y = runs[names[a]], runs[names[b]]
        sv = len(set(x["survivors"]) & set(y["survivors"]))
        fn = len(set(x["final"]) & set(y["final"]))
        print(f"  {names[a]:>8} vs {names[b]:<8}  통과자 겹침 {sv} (통과 {len(x['survivors'])}·{len(y['survivors'])}) · 최종 5 겹침 {fn}/5")

# ---------------------------------------------------------------- B
listing = "\n".join(f"{k}. [{p['source']}] {p['title']}" for k, p in enumerate(P[:40]))
PLAIN = (f"{CRITERIA}\n\n아래 후보를 서로 비교해 중요한 순서대로 상위 5건을 고르세요. "
         "번호만 쉼표로 구분해 답하세요. 설명 금지.")

def plain(_):
    return chat(PLAIN, listing, temperature=TEMP, max_tokens=40).choices[0].message.content

def verdict(txt):
    try:
        nums = [int(x) for x in txt.strip().replace(" ", "").split(",")]   # the course's parse
    except ValueError:
        return "int() 실패"
    if len(nums) != 5:
        return f"{len(nums)}개"
    if any(n < 0 or n >= 40 for n in nums):
        return "범위 밖 번호"
    if len(set(nums)) != 5:
        return "중복 번호"
    return "정상"

fmt = {}
for TEMP in (0.0, 0.7):
    replies = pmap(plain, range(20))
    tally = Counter(verdict(t) for t in replies)
    distinct = Counter(replies)
    fmt[str(TEMP)] = {"tally": dict(tally), "distinct_replies": len(distinct)}
    print(f"\n== 구조화 출력 없이 20회 · temperature {TEMP}")
    print(f"  판정: {dict(tally)} · 서로 다른 답 {len(distinct)}가지")
    for t, c in distinct.most_common(4):
        print(f"    {c:>2}회  {t.strip()[:60]!r}  → {verdict(t)}")

save("step7_result.json", {"runs": runs, "format": fmt})
