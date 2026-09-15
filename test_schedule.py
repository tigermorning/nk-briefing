# -*- coding: utf-8 -*-
"""run.py scheduling helpers. No key, no network, no waiting.

The 07:30 cron started at 09:49 KST on 2026-09-15. The fix fires early,
waits for NK_SEND_AT, and lets a later fallback cron skip if the brief
already went out. A peer review the same day found the fallback resending a
card that went out on a run marked failed, and a check here that would have
failed the day after it was written; both are covered below.
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
real = {"kind": "graph", "run_id": "2026-09-16 07:30", "dry_run": False, "failed": "", "shipped": 3, "sent": True}
rows_cases = [
    ("오늘 실발송", [real], "2026-09-16 07:30"),
    ("dry-run만", [dict(real, dry_run=True)], ""),
    ("실패 공지만 (카드 0장)", [dict(real, failed="모든 뉴스 피드 수집에 실패해", shipped=0)], ""),
    ("피드 전부 사망, 1차 카드는 나감", [dict(real, failed="모든 뉴스 피드 수집에 실패해", shipped=1)], "2026-09-16 07:30"),
    ("검수 장애로 카드 0장", [dict(real, failed="초안 4건이 모두 검수를 통과하지 못해", shipped=0)], ""),
    ("기사 없는 조용한 날", [dict(real, shipped=0)], "2026-09-16 07:30"),
    ("웹훅 발송 안 됨", [dict(real, sent=False)], ""),
    ("그래프가 죽음", [{"kind": "graph", "run_id": "2026-09-16 07:30", "dry_run": False, "error": "RuntimeError"}], ""),
    ("어제 발송", [dict(real, run_id="2026-09-15 09:50")], ""),
    ("측정 행", [{"ts": "2026-09-16T00:00", "g2": {}}], ""),
    ("실패 뒤 예비 실행이 성공", [dict(real, failed="x", shipped=0), dict(real, run_id="2026-09-16 08:12")], "2026-09-16 08:12"),
    ("sent 칸이 없던 옛 행", [{"kind": "graph", "run_id": "2026-09-16 07:30", "dry_run": False, "failed": ""}], "2026-09-16 07:30"),
    ("웹훅 응답 시간 초과 (보냈을 수 있음)", [dict(real, sent="unknown")], "2026-09-16 07:30"),
]
for label, rows, want in rows_cases:
    got = run.sent_today(rows, "2026-09-16")
    assert got == want, (label, got)
    print(f"OK  {label:<26} {got or '보내야 함'}")

# the real log reads. Only past dates are checked: a check against a date the
# bot has not reached yet breaks the day the bot commits that date's row
rows = run.read_rows()
assert rows and run.sent_today(rows, "2026-09-15") == "2026-09-15 09:50", run.sent_today(rows, "2026-09-15")
assert run.sent_today(rows, "2026-09-01") == ""
print("실제 metrics.jsonl: 09-15 발송 인식, 첫 실행 전 날짜는 보내야 함")

# a broken line in the metrics log is skipped, not fatal
import os, tempfile
fd, tmp = tempfile.mkstemp(suffix=".jsonl")
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    fh.write('{"kind": "graph", "run_id": "2026-09-16 07:30", "dry_run": false, "failed": "", "sent": true}\n')
    fh.write('<<<<<<< HEAD\n{"kind": "gra\n')
got = run.read_rows(tmp)
os.remove(tmp)
assert len(got) == 1 and run.sent_today(got, "2026-09-16") == "2026-09-16 07:30", got
print("깨진 기록 줄은 건너뜀 OK")

# a corrupt ledger stops the run instead of reading as empty
import min_publish
real_ledger = min_publish.LEDGER
fd, tmp = tempfile.mkstemp(suffix=".json")
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    fh.write('{"https://a": "2026-09-15T00:00:00"')      # cut off
min_publish.LEDGER = tmp
try:
    min_publish.load_ledger()
    raise AssertionError("corrupt ledger read as a value")
except RuntimeError:
    pass
min_publish.LEDGER = tmp + ".missing"
assert min_publish.load_ledger() == {}
fresh = tmp + ".fresh.json"
min_publish.LEDGER = fresh
min_publish.mark_published([{"link": "https://b"}])
assert min_publish.load_ledger().keys() == {"https://b"} and not os.path.exists(fresh + ".tmp")
min_publish.LEDGER = real_ledger
os.remove(tmp); os.remove(fresh)
print("깨진 원장은 멈춤, 없는 원장은 빈 원장 OK")

# preflight
errs, warns = run.preflight({}, dry=True)
assert len(errs) == 1 and "OPENAI_API_KEY" in errs[0] and len(warns) == 1, (errs, warns)
errs, _ = run.preflight({"OPENAI_API_KEY": "x", "DATA_GO_KR_KEY": "y"}, dry=False)
assert len(errs) == 1 and "DISCORD_WEBHOOK_URL" in errs[0], errs
assert run.preflight({"OPENAI_API_KEY": "x", "DATA_GO_KR_KEY": "y", "DISCORD_WEBHOOK_URL": "z"}, dry=False) == ([], [])
print("실행 전 점검 OK")
print("ALL OK")
