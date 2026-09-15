# -*- coding: utf-8 -*-
"""One briefing run. GitHub Actions calls this every morning.

Locally the keys come from the .env named in graph.ENV (NK_ENV_FILE, else this
repo's .env; copy .env.example); in Actions they come from repository secrets.
Only DRY_RUN=0 sends, so a local run never posts.
Exit code 1 when the run published a failure notice, so Actions goes red.
Exit code 2 when a required key is missing, before anything is fetched.

Scheduled runs only (daily.yml sets these for the schedule event):
  NK_SEND_AT=07:30   wait until this KST time before collecting. GitHub
                     started the 07:30 cron at 09:49 on 2026-09-15, so the
                     cron now fires early and the run waits for the hour.
  NK_ONCE_A_DAY=1    skip if today's brief already went out. A second, later
                     cron is the fallback for a dropped, late or failed first one.
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
    # sent is True, False, "unknown" (webhook read timeout: counts as sent) or
    # missing on rows written before 2026-09-15
    """The run_id of today's brief if it went out, or "".

    Counts as sent: a real run whose webhook post succeeded and that either
    shipped cards or was a normal (possibly empty) day. Does not count: dry
    runs, crashes, a post that never happened (sent False), and a failure
    notice with no cards -- the fallback run should retry after those.

    Peer review 2026-09-15: a run that shipped the tier1 card with every feed
    dead was marked failed and ignored here, so the fallback sent it again."""
    for r in rows:
        if (r.get("kind") != "graph" or r.get("dry_run") is not False or r.get("error")
                or not str(r.get("run_id", "")).startswith(today)):
            continue
        if r.get("sent") is False:
            continue
        if r.get("failed") and not r.get("shipped"):
            continue
        return r["run_id"]
    return ""


def read_rows(path=METRICS):
    """Rows of the metrics log. A line that does not parse (a cut-off append,
    a leftover conflict marker) is skipped with a warning instead of stopping
    both scheduled runs before they send."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                print(f"주의: {path} {n}번째 줄을 읽을 수 없어 건너뜀", flush=True)
    return rows


def preflight(env=os.environ, dry=True):
    """(errors, warnings) before any network call. A missing key used to show
    up as an OpenAI traceback halfway through select, after the feeds were
    fetched, with a CRASH row in the tracked metrics file."""
    errors, warnings = [], []
    if not env.get("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY가 없습니다. .env.example을 .env로 복사해 키를 넣거나 NK_ENV_FILE로 경로를 지정하세요.")
    if not dry and not env.get("DISCORD_WEBHOOK_URL"):
        errors.append("DRY_RUN=0인데 DISCORD_WEBHOOK_URL이 없습니다.")
    # only a briefing with a tier1 slot needs the MOU key
    if graph.CFG["일차칸"] and not env.get("DATA_GO_KR_KEY"):
        warnings.append("DATA_GO_KR_KEY가 없어 통일부 1차 칸은 DEAD로 기록됩니다.")
    return errors, warnings


if __name__ == "__main__":
    graph.load_env()
    hook = bool(os.environ.get("DISCORD_WEBHOOK_URL"))      # presence only, never the value
    print("모드:", "dry-run" if graph.is_dry() else "발행", "· 웹훅 주소", "있음" if hook else "없음", flush=True)
    now = datetime.now(graph.KST)
    # an already-sent day ends green even if a secret has since gone missing
    if os.environ.get("NK_ONCE_A_DAY") == "1":
        done = sent_today(read_rows(), now.strftime("%Y-%m-%d"))
        if done:
            print(f"오늘 이미 발송한 기록이 있어 건너뜀 (run_id {done})", flush=True)
            sys.exit(0)
    errors, warnings = preflight(dry=graph.is_dry())
    for w in warnings:
        print("주의:", w, flush=True)
    if errors:
        for e in errors:
            print("오류:", e, flush=True)
        sys.exit(2)
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
