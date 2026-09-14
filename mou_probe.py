# -*- coding: utf-8 -*-
"""Two questions decide whether the MOU API can hold the tier1 slot:
   freshness -- is today's briefing served, or is the feed days behind?
   novelty   -- does it carry signals the RSS sources do not?
Console is cp949 here, so the readable report goes to a UTF-8 file."""
import io, sys
from datetime import datetime
from mou_api import get_trend

sys.stdout.reconfigure(errors="replace")
today = datetime.now()
out = []

for period, days in [("daily", 30), ("weekly", 60), ("monthly", 180)]:
    res = get_trend(period, days, rows=30)
    if "error" in res:
        out.append(f"## {period}: ERROR {res['error']} {res.get('msg','')}")
        print(f"{period:<9} ERROR {res['error']}")
        continue
    items = res.get("items", []) or []
    dates = sorted({i.get("first_reg_ymd") for i in items if i.get("first_reg_ymd")})
    lag = "-"
    if dates:
        newest = datetime.strptime(dates[-1], "%Y%m%d")
        lag = (today - newest).days
    print(f"{period:<9} total={res.get('totalCount')} items={len(items)} "
          f"newest={dates[-1] if dates else '-'} lag_days={lag}")
    out.append(f"\n## {period}  total={res.get('totalCount')}  items={len(items)}"
               f"  newest={dates[-1] if dates else '-'}  lag_days={lag}")
    out.append(f"dates: {', '.join(dates)}")
    for i in items[:4]:
        out.append(f"\n- [{i.get('first_reg_ymd')}] {i.get('sj')}")
        out.append(f"  cn ({len(i.get('cn') or '')}자): {(i.get('cn') or '')[:400]}")
        out.append(f"  url: {i.get('url')}")

io.open("mou_report.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n-> mou_report.txt")
