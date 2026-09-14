# -*- coding: utf-8 -*-
"""Course step 8 on North Korea articles.

  A  Korean on the first try: 9 bodies (6 Japanese, 1 English, 2 Korean),
     drafted with the course's original instruction (no "write in Korean"
     line) and with the pipeline's SYS_DRAFT (which has it). A field with
     no Hangul gets one retry with an explicit "rewrite in Korean".
  B  temperature 0 vs 0.7, three drafts each, on the Japanese price survey
     (number-heavy) and the English 38North piece: identical headlines,
     and whether the numbers in the summary stay the same.
"""
import re
from collections import Counter
from common import load, save, pmap, short
import graph

B = load("bodies.json")
KO = re.compile(r"[가-힣]")
FIELDS = ("headline", "summary", "why")

COURSE_SYS = ("당신은 북한 뉴스 브리핑 기자입니다.\n"
              "아래 기사 본문을 읽고 헤드라인·요약·왜 중요한지를 쓰세요.\n"
              "'주목된다·기대를 모은다' 같은 기자체 표현은 쓰지 마세요.")
PIPE_SYS = graph.SYS_DRAFT
RETRY = "\n반드시 한국어로 다시 쓰세요."

def english_fields(d):
    return [k for k in FIELDS if not KO.search(getattr(d, k))]

def draft(body, system, temperature=0.0):
    return graph.llm().chat.completions.parse(
        model=graph.MODEL, temperature=temperature,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": body[:6000]}],
        response_format=graph.Draft).choices[0].message.parsed

def with_retry(args):
    b, system = args
    d = draft(b["body"], system)
    bad = english_fields(d)
    if not bad:
        return {"first": [], "after": [], "headline": d.headline}
    d2 = draft(b["body"], system + RETRY)
    return {"first": bad, "after": english_fields(d2), "headline": d2.headline}

res = {}
print("== A. 첫 시도에 한글 없는 칸 → 1회 재요청")
for name, system in (("강의 지시문", COURSE_SYS), ("파이프라인 SYS_DRAFT", PIPE_SYS)):
    out = pmap(with_retry, [(b, system) for b in B])
    res[name] = out
    print(f"\n  [{name}]")
    for b, o in zip(B, out):
        state = "첫 시도 통과" if not o["first"] else ("재시도 후 통과" if not o["after"] else "재시도 후에도 실패")
        print(f"    {b['source']:<11} {len(b['body']):>5}자  {state:<12} {o['first'] or ''}  {short(o['headline'], 30)}")
    bad = sum(1 for o in out if o["first"])
    fixed = sum(1 for o in out if o["first"] and not o["after"])
    by_lang = Counter(b["source"] for b, o in zip(B, out) if o["first"])
    print(f"    첫 시도 실패 {bad}/{len(B)} · 재요청으로 고쳐짐 {fixed}/{bad} · 실패 소스 {dict(by_lang)}")

print("\n== B. temperature 0 vs 0.7, 3회씩")
NUM = re.compile(r"\d[\d,\.]*")
targets = [b for b in B if "価格調査で探る北朝鮮経済（8）" in b["title"]] + [b for b in B if b["source"] == "38North"]
temp_res = {}
for b in targets:
    print(f"\n  {b['source']} · {short(b['title'], 40)}")
    for temp in (0.0, 0.7):
        ds = pmap(lambda _: draft(b["body"], PIPE_SYS, temp), range(3))
        heads = Counter(d.headline for d in ds)
        nums = [tuple(sorted(set(NUM.findall(d.summary)))) for d in ds]
        lens = [len(d.summary) for d in ds]
        temp_res[f"{b['source']}@{temp}"] = {"headlines": [d.headline for d in ds], "numbers": nums, "lens": lens}
        print(f"    temperature {temp}: 헤드라인 {len(heads)}가지 · 요약 숫자 조합 {len(set(nums))}가지 · 요약 길이 {lens}")
        for d in ds:
            print(f"      - {short(d.headline, 50)}  숫자 {sorted(set(NUM.findall(d.summary)))}")

save("step8_result.json", {"A": res, "B": temp_res})
