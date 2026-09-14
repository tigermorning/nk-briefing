# -*- coding: utf-8 -*-
"""Course step 9, applied to a North Korea source: the digit-matching check
(every number in the summary must appear in the source text). No key.

Real text: AsiaPress price survey part 8 (Japanese) and a DailyNK Japan
headline. The Korean summaries are written by hand from that text -- three
faithful ones that differ only in how the numbers are written, and two
fakes. The point is which of them the check gets right.
"""
import re, sys
import requests, trafilatura

sys.stdout.reconfigure(errors="replace")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0"}

def missing_numbers(summary, body):          # the course's check, unchanged
    nums = sorted(set(re.findall(r"\d[\d,\.]*", summary)))
    return [n for n in nums if n.replace(",", "") not in body.replace(",", "")]

r = requests.get("https://www.asiapress.org/apn/2026/09/north-korea/price-survey-8/", headers=UA, timeout=25)
r.raise_for_status()
asiapress = trafilatura.extract(r.content) or ""
assert "3万5000～7万ウォン" in asiapress, "article text changed; re-read it before trusting this test"
dailynk_jp = "北朝鮮女性、性的被害の生々しい証言「ひと月に５～６回も襲われた」"   # feed title as published

CASES = [  # label, faithful?, summary, source text
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

right = 0
print(f"{'경우':<16}{'실제':<6}{'판정':<8}원문에 없는 숫자")
for label, faithful, summary, body in CASES:
    miss = missing_numbers(summary, body)
    verdict = "합격" if not miss else "불합격"
    correct = (verdict == "합격") == faithful
    right += correct
    print(f"{label:<16}{'정상' if faithful else '가짜':<6}{verdict:<8}{miss}  {'' if correct else '← 틀림'}")
print(f"\n맞힌 판정 {right}/{len(CASES)}")
