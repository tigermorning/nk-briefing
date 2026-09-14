# -*- coding: utf-8 -*-
"""tier1 slot rule: the MOU trend API has no full text anywhere, so the slot
opens only on days whose summary is long enough to stand on its own.

An empty slot has two very different causes and they must not share a status:
  BELOW_BAR      -- items were published, none reached CN_MIN. The rule worked.
  NO_PUBLICATION -- nothing was published that day (weekend, holiday, not yet up).
  DEAD           -- the API failed. Silence here is a failure, not a quiet day.
Collapsing these into "no tier1 today" is how a dead API survives for weeks.
"""
import sys
from datetime import datetime, timedelta
from mou_api import get_trend

sys.stdout.reconfigure(errors="replace")

CN_MIN = 300

def tier1_for(day, by_day):
    """day: 'YYYYMMDD'. by_day: {day: [items]} as returned by the API."""
    items = by_day.get(day)
    if items is None:
        return "NO_PUBLICATION", None
    good = [i for i in items if len(i.get("cn") or "") >= CN_MIN]
    if not good:
        return "BELOW_BAR", None
    return "OPEN", max(good, key=lambda i: len(i.get("cn") or ""))

def load(days=30):
    res = get_trend("daily", days, rows=200)
    if "error" in res:
        return None, res
    by_day = {}
    for i in res.get("items", []) or []:
        by_day.setdefault(i.get("first_reg_ymd"), []).append(i)
    return by_day, None

if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    by_day, err = load(days)
    if by_day is None:
        print(f"DEAD: {err.get('error')} {err.get('msg','')}")
        raise SystemExit(1)

    WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    today = datetime.now()
    print(f"{'date':<10}{'wd':<5}{'items':>6}{'max_cn':>8}  {'status':<15}title")
    print("-" * 78)
    counts = {}
    for k in range(days, -1, -1):
        d = today - timedelta(days=k)
        key = d.strftime("%Y%m%d")
        status, pick = tier1_for(key, by_day)
        items = by_day.get(key, [])
        maxcn = max((len(i.get("cn") or "") for i in items), default=0)
        weekend = d.weekday() >= 5
        if status == "NO_PUBLICATION" and weekend:
            status = "WEEKEND"
        counts[status] = counts.get(status, 0) + 1
        print(f"{key:<10}{WD[d.weekday()]:<5}{len(items):>6}{maxcn:>8}  {status:<15}"
              f"{(pick.get('sj') if pick else '')[:24]}")

    print()
    print("tally:", counts)
    opened = counts.get("OPEN", 0)
    weekdays = sum(v for k, v in counts.items() if k != "WEEKEND")
    print(f"slot opened {opened}/{weekdays} non-weekend days "
          f"({100*opened/weekdays:.0f}%)  CN_MIN={CN_MIN}")
    print("BELOW_BAR is the rule working. NO_PUBLICATION on a weekday is worth a look.")
