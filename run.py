# -*- coding: utf-8 -*-
"""One briefing run. GitHub Actions calls this every morning.

Locally the keys come from the .env named in graph.ENV; in Actions they come
from repository secrets. Only DRY_RUN=0 sends, so a local run never posts.
Exit code 1 when the run published a failure notice, so Actions goes red.

Scheduled runs only (daily.yml sets these for the schedule event):
  NK_SEND_AT=07:30   wait until this KST time before collecting. GitHub
                     started the 07:30 cron at 09:49 on 2026-09-15, so the
                     cron now fires early and the run waits for the hour.
  NK_ONCE_A_DAY=1    skip if a real send already went out today. A second,
                     later cron is the fallback for a dropped or late first one.
"""
import json, os, re, sys, time
from datetime import datetime, timedelta
import graph
from collect_nk import METRICS


def seconds_until(now, hhmm):
    """Seconds from now (KST) to today's hh:mm; 0 once it has passed."""
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", hhmm)
    if not m:
        raise ValueError(f"NK_SEND_AT must be HH:MM, got {hhmm!r}")
    target = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    return max(0.0, (target - now).total_seconds())


def sent_today(rows, today):
    """The run_id of today's real send, or "". A dry run, a crash or a failure
    notice does not count -- the fallback run should try again after those."""
    for r in rows:
        if (r.get("kind") == "graph" and r.get("dry_run") is False and not r.get("failed")
                and not r.get("error") and str(r.get("run_id", "")).startswith(today)):
            return r["run_id"]
    return ""


def read_rows(path=METRICS):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


if __name__ == "__main__":
    graph.load_env()
    hook = bool(os.environ.get("DISCORD_WEBHOOK_URL"))      # presence only, never the value
    print("모드:", "dry-run" if graph.is_dry() else "발행", "· 웹훅 주소", "있음" if hook else "없음", flush=True)

    now = datetime.now(graph.KST)
    if os.environ.get("NK_ONCE_A_DAY") == "1":
        done = sent_today(read_rows(), now.strftime("%Y-%m-%d"))
        if done:
            print(f"오늘 이미 발송한 기록이 있어 건너뜀 (run_id {done})", flush=True)
            sys.exit(0)
    send_at = os.environ.get("NK_SEND_AT", "").strip()
    if send_at:
        wait = seconds_until(now, send_at)
        if wait:
            start = (now + timedelta(seconds=wait)).strftime("%H:%M")
            print(f"{send_at} 발송 예정 · {wait / 60:.0f}분 기다린 뒤 {start}에 수집 시작", flush=True)
            time.sleep(wait)
        else:
            print(f"{send_at}이 지나 바로 시작 (현재 {now:%H:%M})", flush=True)

    out = graph.run()
    for line in out["log"]:
        print(line)
    if out["meta"].get("failed"):
        sys.exit(1)
