# -*- coding: utf-8 -*-
"""Course step 9, second half: the LLM check (graph.check) on the same five
hand-written summaries that the digit-matching check got 1 of 5 right
(test_number_check.py). Three runs each at temperature 0.
"""
import sys, pathlib
from common import pmap
import graph

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import requests, trafilatura

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"}
r = requests.get("https://www.asiapress.org/apn/2026/09/north-korea/price-survey-8/", headers=UA, timeout=25)
r.raise_for_status()
asiapress = trafilatura.extract(r.content) or ""
assert "3万5000～7万ウォン" in asiapress
dailynk_jp = "北朝鮮女性、性的被害の生々しい証言「ひと月に５～６回も襲われた」"

HEAD = {"asiapress": "국영기업 노임 인상 뒤 물가 급등", "dailynk_jp": "북한 여성, 반복된 성폭력 피해 증언"}
CASES = [  # label, faithful?, summary, source  -- same texts as test_number_check.py
    ("원문 표기 그대로", True,
     "2023년 말 국영기업 노임이 10배 이상 올라 1500~2500원에서 3만5000~7만원이 됐습니다. "
     "인상 직후보다 쌀은 6.5배, 옥수수는 5.5배 올랐습니다.", asiapress),
    ("만 단위를 풀어 씀", True,
     "2023년 말 국영기업 노임이 10배 이상 올라 1,500~2,500원에서 35,000~70,000원이 됐습니다.", asiapress),
    ("전각 숫자 원문", True,
     "한 북한 여성은 한 달에 5~6회 피해를 당했다고 증언했습니다.", dailynk_jp),
    ("가짜: 없는 배율", False,
     "2023년 말 국영기업 노임이 20배 올라 3만5000~7만원이 됐습니다.", asiapress),
    ("가짜: 숫자 자리만 바꿈", False,
     "인상 직후보다 쌀은 5.5배, 옥수수는 6.5배 올랐습니다.", asiapress),
]

def judge(case):
    label, faithful, summary, body = case
    vs = pmap(lambda _: graph.check({"body": body, "headline": HEAD["dailynk_jp" if body is dailynk_jp else "asiapress"], "summary": summary}), range(3), workers=3)
    return case, vs

right = 0
print(f"{'경우':<16}{'실제':<6}{'LLM 3회':<14}문제로 짚은 부분(1회차)")
for (label, faithful, summary, body), vs in pmap(judge, CASES, workers=5):
    oks = ["합격" if v.ok else "불합격" for v in vs]
    majority = oks.count("합격") >= 2
    right += majority == faithful
    probs = "; ".join(vs[0].problems)[:70]
    print(f"{label:<16}{'정상' if faithful else '가짜':<6}{'·'.join(oks):<14}{probs}")
print(f"\n다수결로 맞힌 판정 {right}/{len(CASES)} (숫자 대조는 1/5)")
