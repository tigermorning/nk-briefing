# -*- coding: utf-8 -*-
"""Which retry actually gets Korean out of the one DailyNK Japan body that
stayed Japanese even after the pipeline's retry (step8_drafts.py)?

  now     SYS_DRAFT + "반드시 한국어로 다시 쓰세요." (what graph.draft does)
  user    SYS_DRAFT, and the user message opens with a line naming the
          source language and the output language
  both    both of the above
Three drafts each at temperature 0, plus the same three on every other
non-Korean body as a regression check.
"""
import re
from common import load, pmap, short
import graph

B = load("bodies.json")
KO = re.compile(r"[가-힣]")
ok = lambda d: d is not None and all(KO.search(getattr(d, k)) for k in ("headline", "summary", "why"))
HEAD = "[아래는 {lang} 기사 본문입니다. 헤드라인·요약·왜 중요한지를 모두 한국어로만 쓰세요.]\n\n"
LANG = {"DailyNK-JP": "일본어", "AsiaPress": "일본어", "38North": "영어"}

def run(args):
    b, mode = args
    system = graph.SYS_DRAFT + ("\n반드시 한국어로 다시 쓰세요." if mode in ("now", "both") else "")
    user = (HEAD.format(lang=LANG.get(b["source"], "외국어")) if mode in ("user", "both") else "") + b["body"][:6000]
    return graph.parse(system, user, graph.Draft)

stubborn = [b for b in B if "クラスター弾" in b["title"]]
foreign = [b for b in B if b["source"] in LANG and b not in stubborn]
for label, group in (("고집 센 1건", stubborn), (f"나머지 외국어 {len(foreign)}건", foreign)):
    print(f"\n== {label}")
    for mode in ("now", "user", "both"):
        jobs = [(b, mode) for b in group for _ in range(3)]
        outs = pmap(run, jobs)
        good = sum(ok(d) for d in outs)
        print(f"  {mode:<5} 한국어 {good}/{len(outs)}  예: {short(outs[0].headline if outs[0] else '', 40)}")
