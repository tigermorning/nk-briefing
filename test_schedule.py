# -*- coding: utf-8 -*-
"""run.py scheduling helpers. No key, no network, no waiting.

The 07:30 cron started at 09:49 KST on 2026-09-15. The fix fires early,
waits for NK_SEND_AT, and lets a later fallback cron skip if the send
already went out.
"""
import sys
from datetime import datetime
import graph
import run

sys.stdout.reconfigure(errors="replace")
KST = graph.KST

def at(h, m, s=0):
    return datetime(2026, 9, 16, h, m, s, tzinfo=KST)

# waiting
assert run.seconds_until(at(5, 43), "07:30") == 107 * 60
assert run.seconds_until(at(7, 29, 30), "07:30") == 30
assert run.seconds_until(at(7, 30), "07:30") == 0
assert run.seconds_until(at(9, 49), "07:30") == 0           # a late start goes straight on
for bad in ("7:30", "07:3", "24:00", "07-30", ""):
    try:
        run.seconds_until(at(5, 43), bad)
        raise AssertionError(f"accepted {bad!r}")
    except ValueError:
        pass
print("대기 계산 OK")

# once a day
real = {"kind": "graph", "run_id": "2026-09-16 07:30", "dry_run": False, "failed": ""}
rows_cases = [
    ("오늘 실발송", [real], "2026-09-16 07:30"),
    ("dry-run만", [dict(real, dry_run=True)], ""),
    ("실패 공지만", [dict(real, failed="모든 뉴스 피드 수집에 실패해")], ""),
    ("그래프가 죽음", [{"kind": "graph", "run_id": "2026-09-16 07:30", "dry_run": False, "error": "RuntimeError"}], ""),
    ("어제 발송", [dict(real, run_id="2026-09-15 09:50")], ""),
    ("측정 행", [{"ts": "2026-09-16T00:00", "g2": {}}], ""),
    ("실패 뒤 예비 실행이 성공", [dict(real, failed="x"), dict(real, run_id="2026-09-16 08:12")], "2026-09-16 08:12"),
]
for label, rows, want in rows_cases:
    got = run.sent_today(rows, "2026-09-16")
    assert got == want, (label, got)
    print(f"OK  {label:<22} {got or '보내야 함'}")

# the real log reads, and yesterday's real send does not block today
rows = run.read_rows()
assert rows and run.sent_today(rows, "2026-09-15") == "2026-09-15 09:50", run.sent_today(rows, "2026-09-15")
assert run.sent_today(rows, "2026-09-16") == ""
print("실제 metrics.jsonl: 09-15 발송 인식, 09-16은 보내야 함")
print("ALL OK")
