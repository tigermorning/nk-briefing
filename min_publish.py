# -*- coding: utf-8 -*-
"""Minimum-publish rule.

Widening the window is the obvious answer to a lean day, and it has a trap:
a 48h window re-collects everything yesterday's briefing already carried. So
escalation is only safe on top of a ledger of what has actually been
published, and the widened window is reported rather than hidden -- a reader
told "today" deserves to know when the net was cast over three days.

If even the widest window is short, we publish short. Padding a briefing with
older material to hit a number is the failure this whole pipeline is built to
avoid.
"""
import io, json, os, sys
from datetime import datetime, timezone
from collect_nk import collect, link_key, STORE

sys.stdout.reconfigure(errors="replace")

LEDGER = os.path.join(STORE, "published.json")
MIN_ITEMS = 5
LADDER = (24, 48, 72)

def load_ledger():
    try:
        with io.open(LEDGER, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

def mark_published(items):
    """Call this from the publish step, not from collection -- an item that was
    collected but never published must stay eligible tomorrow."""
    led = load_ledger()
    stamp = datetime.now(timezone.utc).isoformat()
    for it in items:
        key = link_key(it.get("link") or "")
        if key:                                 # "" would mark every link-less item as published
            led.setdefault(key, stamp)
    os.makedirs(STORE, exist_ok=True)
    with io.open(LEDGER, "w", encoding="utf-8") as fh:
        json.dump(led, fh, ensure_ascii=False, indent=1)
    return len(led)

def gather(min_items=MIN_ITEMS, ladder=LADDER):
    led = load_ledger()
    steps = []
    for hours in ladder:
        res = collect({"hours": hours})
        fresh = [i for i in res["items"]
                 if link_key(i["link"]) not in led]
        steps.append({"hours": hours, "collected": len(res["items"]),
                      "unpublished": len(fresh)})
        if len(fresh) >= min_items:
            return {"items": fresh, "window_h": hours, "steps": steps,
                    "escalated": hours != ladder[0], "below_min": False,
                    "dead": res["dead"], "gaps": res["gaps"],
                    "silent": res["silent"]}
    return {"items": fresh, "window_h": ladder[-1], "steps": steps,
            "escalated": True, "below_min": True,
            "dead": res["dead"], "gaps": res["gaps"], "silent": res["silent"]}

if __name__ == "__main__":
    min_items = int(sys.argv[1]) if len(sys.argv) > 1 else MIN_ITEMS
    res = gather(min_items)
    print(f"ledger holds {len(load_ledger())} already-published links")
    print(f"{'window':>8}{'collected':>11}{'unpublished':>13}")
    for s in res["steps"]:
        print(f"{str(s['hours'])+'h':>8}{s['collected']:>11}{s['unpublished']:>13}")
    print()
    print(f"window used: {res['window_h']}h"
          + ("  (ESCALATED -- say so in the briefing)" if res["escalated"] else ""))
    print(f"items for the briefing: {len(res['items'])}  (min {min_items})")
    if res["below_min"]:
        print("!! BELOW_MIN -- publish short. do not pad with older material")
    for d in res["dead"]:
        print(f"!! DEAD   {d['source']}: {d['reason']}")
    for g in res["gaps"]:
        print(f"!! GAP    {g['source']}")
    by = {}
    for i in res["items"]:
        by[i["source"]] = by.get(i["source"], 0) + 1
    print("by source:", by)
