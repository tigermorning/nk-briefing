# -*- coding: utf-8 -*-
"""Course step 6 on North Korea articles: four ways to pick 5 of 12.

  A  absolute: each title scored 1-10 alone, temperature 0, three runs
  B  absolute at temperature 0.7, three runs -- how far a score swings
  C  relative: all 12 on one screen, top 5 -- listed forward and reversed
  D  tournament: 66 pairs, each asked in both orders (132 calls)

Also: does a Japanese title score lower than a Korean one on the same kind
of news (mean score per source), and where the temperature-0 runs disagree,
what the first-token probabilities were.
"""
import math, re
from collections import Counter, defaultdict
from itertools import combinations
from common import CRITERIA, chat, load, save, pmap, first_int, short

C = load("candidates12.json")
N = len(C)
label = lambda i: f"{i:>2} [{C[i]['source']:<10}] {short(C[i]['title'], 36)}"

RUBRIC = (f"{CRITERIA}\n\n아래 기사 제목이 위 기준에서 얼마나 중요한지 1~10점으로 매기세요. "
          "숫자만 답하세요.")

def score(i, temperature=0.0, logprobs=False):
    r = chat(RUBRIC, C[i]["title"], temperature=temperature, max_tokens=3,
             logprobs=logprobs, top_logprobs=5 if logprobs else None)
    out = {"score": first_int(r.choices[0].message.content)}
    if logprobs:
        top = r.choices[0].logprobs.content[0].top_logprobs
        out["top"] = [(t.token, round(math.exp(t.logprob) * 100, 1)) for t in top]
    return out

def top5(scores):                                # ties broken by list order, as sorted() does
    return [i for i, _ in sorted(enumerate(scores), key=lambda kv: -(kv[1] or 0))[:5]]

result = {}

# ---------------------------------------------------------------- A / B
for key, temp in (("A", 0.0), ("B", 0.7)):
    runs = [[s["score"] for s in pmap(lambda i: score(i, temp), range(N))] for _ in range(3)]
    result[key] = runs
    print(f"\n== {key}. 독립 채점 temperature {temp} · 3회 ({N * 3}번 호출)")
    print("    1회 2회 3회  기사")
    for i in range(N):
        vals = [r[i] for r in runs]
        mark = "  ← 흔들림" if len(set(vals)) > 1 else ""
        print(f"    {vals[0]:>3} {vals[1]:>3} {vals[2]:>3}  {label(i)}{mark}")
    for k, r in enumerate(runs, 1):
        print(f"  {k}회 상위 5: {top5(r)}  · 서로 다른 점수 값 {len(set(r))}개 · 분포 {dict(sorted(Counter(r).items(), reverse=True))}")
    by_src = defaultdict(list)
    for r in runs:
        for i, s in enumerate(r):
            by_src[C[i]["source"]].append(s)
    print("  소스별 평균:", " · ".join(f"{s} {sum(v)/len(v):.2f}" for s, v in by_src.items()))

wobble = [i for i in range(N) if len({r[i] for r in result["A"]}) > 1]
if wobble:
    print("\n  temperature 0에서 흔들린 기사의 첫 토큰 확률")
    for i in wobble:
        p = score(i, 0.0, logprobs=True)
        print(f"    {label(i)}  " + " · ".join(f"'{t}' {pr}%" for t, pr in p["top"][:3]))
        result.setdefault("A_probs", {})[i] = p["top"]

# ---------------------------------------------------------------- C
PICK = (f"{CRITERIA}\n\n아래 후보를 서로 비교해 중요한 순서대로 5건을 고르세요. "
        "번호만 쉼표로 구분해 답하세요. 설명 금지.")

def relative(order):
    listing = "\n".join(f"{k}. [{C[i]['source']}] {C[i]['title']}" for k, i in enumerate(order))
    txt = chat(PICK, listing, max_tokens=30).choices[0].message.content
    return [order[int(x)] for x in re.findall(r"\d+", txt)[:5] if int(x) < N]

fwd, rev = relative(list(range(N))), relative(list(range(N))[::-1])
result["C"] = {"forward": fwd, "reversed": rev}
print(f"\n== C. 한 화면 상대평가 (2번 호출)")
print(f"  정순 목록 상위 5: {fwd}")
print(f"  역순 목록 상위 5: {rev}")
print(f"  겹치는 기사 {len(set(fwd) & set(rev))}/5 · 순위까지 같은 자리 {sum(a == b for a, b in zip(fwd, rev))}/5")

# ---------------------------------------------------------------- D
DUEL = (f"{CRITERIA}\n\n두 기사 중 위 기준에서 더 중요한 쪽은 어느 것입니까? "
        "A 또는 B 한 글자만 답하세요. 설명 금지.")

def duel(first, second):
    user = (f"A. [{C[first]['source']}] {C[first]['title']}\n"
            f"B. [{C[second]['source']}] {C[second]['title']}")
    ans = chat(DUEL, user, max_tokens=2).choices[0].message.content.strip().upper()
    return first if ans.startswith("A") else second

pairs = list(combinations(range(N), 2))
duels = pmap(lambda p: (p, duel(p[0], p[1]), duel(p[1], p[0])), pairs)
agree = [(p, w1) for p, w1, w2 in duels if w1 == w2]
slot = Counter()
wins = Counter()
for (a, b), w1, w2 in duels:
    slot["A"] += (w1 == a) + (w2 == b)
    slot["B"] += (w1 == b) + (w2 == a)
    if w1 == w2:
        wins[w1] += 1
    else:                                        # the pair's verdict depends on order: half each
        wins[a] += 0.5
        wins[b] += 0.5
ranking = sorted(range(N), key=lambda i: -wins[i])
result["D"] = {"agree": len(agree), "pairs": len(pairs), "slot": dict(slot),
               "wins": {i: wins[i] for i in range(N)}, "top5": ranking[:5]}
print(f"\n== D. 토너먼트 {len(pairs)}쌍 × 양방향 ({len(pairs) * 2}번 호출)")
print(f"  두 순서 판정 일치 {len(agree)}/{len(pairs)}쌍 ({len(agree)/len(pairs):.0%})")
print(f"  {len(pairs) * 2}번 중 A 자리 {slot['A']}번 / B 자리 {slot['B']}번")
print("  승수 (순서에 따라 갈린 쌍은 0.5씩)")
for rank, i in enumerate(ranking, 1):
    print(f"    {rank:>2}위 {wins[i]:>4}승  {label(i)}")
ties = Counter(wins[i] for i in ranking[:7])
print("  상위 7위 안 동점:", {k: v for k, v in ties.items() if v > 1} or "없음")
src_wins = defaultdict(float)
for i in range(N):
    src_wins[C[i]["source"]] += wins[i]
print("  소스별 승수 합:", " · ".join(f"{s} {v:g}" for s, v in src_wins.items()))

# ---------------------------------------------------------------- compare
print("\n== 네 방식의 상위 5 비교")
sets = {"A 독립 1회": top5(result["A"][0]), "C 상대 정순": fwd, "C 상대 역순": rev, "D 토너먼트": ranking[:5]}
for k, v in sets.items():
    print(f"  {k:<10} {v}")
names = list(sets)
for x, y in combinations(names, 2):
    print(f"  {x} ∩ {y}: {len(set(sets[x]) & set(sets[y]))}/5")
save("step6_result.json", result)
