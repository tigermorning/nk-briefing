# -*- coding: utf-8 -*-
"""Does verify catch distortion in a real card? Old judge vs new verify.

Input: the Yonhap card sent on 2026-09-15 07:30 KST run (headline and summary
copied from Discord) and its article body, fetched live. Each case plants one
distortion; each is judged 3 times.

  old  = the SYS_CHECK in graph.py before this change: headline + summary only,
         "번역이나 단위 환산은 문제가 아닙니다"
  new  = graph.judge(): grounding.py number and bound checks + the new SYS_CHECK,
         which also reads the why line and writes claim notes before ok

Needs OPENAI_API_KEY (NK_ENV_FILE or graph.ENV). Nothing is published.
    python exp/step12_exaggeration.py > exp/step12_exaggeration.log
"""
import os, pathlib, sys
import requests, trafilatura

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NK_ENV_FILE", str(ROOT / ".env"))
import graph

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
graph.load_env()

URL = "https://www.yna.co.kr/view/AKR20260914169500085"
r = requests.get(URL, headers=graph.UA, timeout=20)
r.raise_for_status()
body = trafilatura.extract(r.content) or ""
for must in ("1만3천", "2천300", "100억달러", "3분의 1", "확실해 보인다"):
    assert must in body, f"article text changed ({must}); re-read it before trusting this run"

OLD_SYS = ("요약이 원문에서 뒷받침되는지 판정하세요.\n"
           "헤드라인과 요약만 보고 판단하고, 번역이나 단위 환산은 문제가 아닙니다.\n"
           "원문이 북한 매체의 주장을 전하는데 요약이 그것을 사실처럼 단정했다면 문제입니다.")

H = "BBC, 북한군 러시아 추가 파병 확실시…GDP 3분의 1에 육박하는 수입 발생"
S = ("BBC는 북한군이 러시아에 최대 5만명 추가 파병할 가능성이 크다고 보도했습니다. "
     "2024년 말부터 파병된 1만3천명 중 사망자 약 2천300명으로 추정되며, 북한은 무기 판매와 파병으로 "
     "약 100억 달러 수입을 올려 GDP의 3분의 1에 육박합니다. 대러 협력은 지정학적 전환을 가져왔고, "
     "북한은 이익이 되는 한 파병을 계속할 것으로 전망됩니다.")
W = ("북한의 러시아 파병과 무기 판매는 북한 경제에 큰 수입원이 되고 있으며, 대외 관계에서 중국 의존을 "
     "줄이는 지정학적 변화를 나타냅니다.")

CASES = [  # label, faithful?, headline, summary, why
    ("실제 발행본", True, H, S, W),
    ("원화 환산 표기", True, H, S.replace("약 100억 달러", "약 100억 달러(약 13조원)"), W),
    ("금액 10배 1,000억", False, H, S.replace("약 100억 달러", "약 1,000억 달러"), W),
    ("금액 10배 1천억", False, H, S.replace("약 100억 달러", "약 1천억 달러"), W),
    ("금액 5배", False, H, S.replace("약 100억 달러", "약 500억 달러"), W),
    ("사망자 10배", False, H, S.replace("약 2천300명", "약 2만3천명"), W),
    ("숫자 대상 바꿈", False, H, S.replace("파병된 1만3천명 중 사망자 약 2천300명", "파병된 2천300명 중 사망자 약 1만3천명"), W),
    ("한정어 제거", False, H, S.replace("최대 5만명 추가 파병할 가능성이 크다고", "5만명을 추가 파병한다고"), W),
    ("전망을 단정으로", False, H, S.replace("계속할 것으로 전망됩니다", "계속할 것이 확실합니다"), W),
    ("추정을 사실로", False, H, S.replace("사망자 약 2천300명으로 추정되며", "사망자는 2천300명이며"), W),
    ("인사이트에 없는 사실", False, H, S, W + " 중국은 이에 반발해 대북 원유 공급을 30% 줄였습니다."),
    ("없는 문장 추가", False, H, S + " 러시아 국방부도 이 추가 파병을 공식 확인했습니다.", W),
]

def old_judge(h, s, w):
    user = f"[원문]\n{body[:5000]}\n\n[헤드라인]\n{h}\n\n[요약]\n{s}"
    v = graph.parse(OLD_SYS, user, graph.Verdict)
    return [] if v.ok else (v.problems or ["사유 없음"])

def new_judge(h, s, w):
    return graph.judge({"body": body[:6000], "headline": h, "summary": s, "why": w})

RUNS = 3
score = {"old": 0, "new": 0}
print(f"model {graph.MODEL} · body {len(body)}자 · {RUNS}회씩\n")
for label, faithful, h, s, w in CASES:
    line = f"{label:<14}{'정상' if faithful else '왜곡':<4}"
    for name, fn in (("old", old_judge), ("new", new_judge)):
        verdicts, last = [], []
        for _ in range(RUNS):
            problems = fn(h, s, w)
            verdicts.append("통과" if not problems else "불합격")
            last = problems or last
        right = sum((v == "통과") == faithful for v in verdicts)
        score[name] += right
        line += f" | {name} {'/'.join(verdicts)}"
    print(line)
    if last:
        print(f"{'':<18}new 마지막 사유: {'; '.join(last)[:150]}")
total = RUNS * len(CASES)
print(f"\n맞힌 판정  old {score['old']}/{total} · new {score['new']}/{total}")


# Would a bigger judge model see hedges the code cannot? LLM verdict only, no
# code checks, same SYS_CHECK. Measured 2026-09-15 (final run in the log): gpt-4.1
# caught the dropped bound 3 of 3 but the two hedge cases only 1 and 2 of 3, and
# failed the real card 1 of 3. Noisier on faithful cards, so the judge stays mini
# and the figures are left to grounding.py.
COMPARE = {"실제 발행본", "원화 환산 표기", "숫자 대상 바꿈", "한정어 제거", "전망을 단정으로", "추정을 사실로"}
print("\n== LLM 판정만: 모델 비교 ==")
for model in ("gpt-4.1-mini", "gpt-4.1"):
    for label, faithful, h, s, w in CASES:
        if label not in COMPARE:
            continue
        user = f"[원문]\n{body[:5000]}\n\n[헤드라인]\n{h}\n\n[요약]\n{s}\n\n[왜 중요한지]\n{w}"
        vs = [graph.llm().chat.completions.parse(
                  model=model, temperature=0, response_format=graph.Verdict,
                  messages=[{"role": "system", "content": graph.SYS_CHECK}, {"role": "user", "content": user}]
              ).choices[0].message.parsed for _ in range(RUNS)]
        print(f"{model:<13}{label:<14}{'정상' if faithful else '왜곡':<4} {'/'.join('통과' if v.ok else '불합격' for v in vs)}")
