# -*- coding: utf-8 -*-
"""North Korea briefing as one LangGraph run.

  collect -> select -> report (one worker per article) -> verify -> publish

Three slots, each with its own entry rule:
  breaking -- daily feeds, 24h window widened to 48h/72h only when short,
              ranked by the model, only items it ties to an importance
              criterion; TARGET drafted, trimmed at publish to fit the brief
  deep     -- weekly analysis (38North), looked back 7 days, at most one,
              no competition against the daily news
  tier1    -- MOU trend API, opens only when a summary clears CN_MIN,
              at most one, exempt from ranking but still verified

Every run appends one row to store/metrics.jsonl. Nothing is sent unless
DRY_RUN=0, and the published ledger is written only after a real send.
"""
import json, math, operator, os, pathlib, re, sys, time
from datetime import datetime, timedelta, timezone
from typing import Annotated, TypedDict

import requests, trafilatura, yaml
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from pydantic import BaseModel, Field

from collect_nk import (collect as collect_feeds, link_key, load_seen,
                        SOURCES, STORE, METRICS, SEEN, UA)
from min_publish import load_ledger, mark_published, MIN_ITEMS, LADDER

sys.stdout.reconfigure(errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
ENV = os.environ.get("NK_ENV_FILE",
                     r"C:\Users\user\Documents\tigermorning.github.io\ko\.env")

MODEL = os.environ.get("NK_MODEL", "gpt-4.1-mini")
BATCH, PRELIM = 40, 8                # prelim chunk size, kept per chunk
# reader's rule 2026-09-14: 3 cards a day, a deep or tier1 item takes one of
# the three, and only the day both run gets a fourth
BRIEF_SIZE, BRIEF_MAX = 3, 4
TARGET = BRIEF_SIZE + 1              # breaking drafts: a spare for a draft or check that drops out
MAX_PER_SOURCE = 3                   # Yonhap alone fills the feed 9:1 otherwise
BODY_MIN = 600                       # G1
WEEKLY = {"38North", "AsiaPress"}    # deep slot sources
DEEP_WINDOW_H = 168
TIER1_LOOKBACK_D = 4                 # MOU publishes weekdays with a 1 business day lag


def load_env():
    """Fill missing variables from the local .env. Values are never printed.
    An empty variable counts as missing -- a blank OPENAI_API_KEY left in the
    environment would otherwise block the file silently."""
    p = pathlib.Path(ENV)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        if not os.environ.get(k.strip()):
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


# ---------------------------------------------------------------- config
from pydantic import ConfigDict, ValidationError, constr

Text = constr(strip_whitespace=True, min_length=1)

class ReaderCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    누구: Text
    이미_아는_것: Text

class TopicCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    이름: Text
    데스크지침: Text
    색: constr(pattern=r"^#[0-9A-Fa-f]{6}$") = "#5F7476"

class AudienceCfg(BaseModel):
    # extra="forbid": a misspelled key ("버릴것") would otherwise be ignored and
    # the run would go on with no discard rules at all
    model_config = ConfigDict(extra="forbid")
    독자: ReaderCfg
    중요도_기준: list[Text] = Field(min_length=1)
    버릴_것: list[Text]
    토픽: list[TopicCfg] = Field(min_length=1)

def load_cfg(path=HERE / "audience.yaml"):
    # check the shape at start-up: a typo should stop the run here, not at
    # 07:30 halfway through the graph after the model has already been paid
    try:
        cfg = AudienceCfg.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except ValidationError as exc:
        lines = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        raise SystemExit("audience.yaml 오류\n  " + "\n  ".join(lines)) from None
    names = [t.이름 for t in cfg.토픽]
    if len(names) != len(set(names)):
        raise SystemExit("audience.yaml 오류\n  토픽: 이름이 겹침")
    return cfg.model_dump()

CFG = load_cfg()
TOPICS = {t["이름"]: t for t in CFG["토픽"]}
DEFAULT_COLOR = 0x5F7476

def build_criteria(cfg):
    out = [f"독자는 {cfg['독자']['누구']}입니다.",
           f"이미 아는 것: {cfg['독자']['이미_아는_것']}",
           "", "중요도 기준 (위에 있을수록 우선):"]
    out += [f"{k}. {x}" for k, x in enumerate(cfg["중요도_기준"], 1)]
    out += ["", "버릴 것:"]
    out += [f"- {x}" for x in cfg["버릴_것"]]
    return "\n".join(out)

CRITERIA = build_criteria(CFG)
SYS_DRAFT = (f"당신은 북한 뉴스 브리핑 기자입니다. 독자는 {CFG['독자']['누구']}입니다.\n"
             "아래 기사 본문을 읽고 헤드라인·요약·왜 중요한지·토픽을 쓰세요.\n"
             "원문에 없는 사실은 쓰지 마세요. 요약과 왜 중요한지는 '~합니다'체로 끝내세요. "
             "반드시 한국어로 쓰고, "
             "'주목된다·기대를 모은다' 같은 기자체 표현은 쓰지 마세요.\n\n"
             "토픽은 아래 이름 중 하나를 그대로 고르고, 그 토픽의 지침을 따르세요.\n"
             + "\n".join(f"- {n}: {t['데스크지침']}" for n, t in TOPICS.items()))
SYS_CHECK = ("요약이 원문에서 뒷받침되는지 판정하세요.\n"
             "헤드라인과 요약만 보고 판단하고, 번역이나 단위 환산은 문제가 아닙니다.\n"
             "원문이 북한 매체의 주장을 전하는데 요약이 그것을 사실처럼 단정했다면 문제입니다.")


# ---------------------------------------------------------------- model
_client = None
def llm():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI()
    return _client

def parse(system, user, schema):
    return llm().chat.completions.parse(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format=schema).choices[0].message.parsed


class Pick(BaseModel):
    index: int = Field(description="후보 목록에서의 번호")
    reason: str = Field(description="왜 골랐는지 한 문장")
    # measured 2026-09-14: "짧은 라벨" produced field names ("북한 내부 생활 상황")
    # and the code-level dedupe then cut three different DailyNK stories as one
    event: str = Field(description="이 기사가 다루는 구체적인 사건 하나. '누가 무엇을 했다' 모양으로 "
                                   "(예: '북, 9일 동해상 탄도미사일 발사'). '군사 동향'·'내부 생활' 같은 "
                                   "분야 이름은 금지. 같은 사건을 다룬 기사끼리만 같은 문장")
    # measured 2026-09-14: "최대 N건" still came back full, and a DailyNK
    # sketch of residents cooling off in parks went out 3rd of 5. A number the
    # code can check makes "none of the criteria" a drop, not a filler
    criterion: int = Field(description="이 기사가 실제로 해당하는 중요도 기준 번호(1부터). 어느 기준에도 해당하지 않으면 0")

class Shortlist(BaseModel):
    picks: list[Pick]

class Draft(BaseModel):
    headline: str = Field(description="30자 안쪽 한국어 헤드라인")
    summary: str = Field(description="세 문장 요약. ~합니다체, 원문에 있는 사실만")
    why: str = Field(description="독자에게 왜 중요한지 한 문장")
    topic: str = Field(description="지시문에 적힌 토픽 이름 중 하나")

class Verdict(BaseModel):
    ok: bool = Field(description="요약이 원문에 근거하면 true")
    problems: list[str] = Field(description="근거 없는 부분. 없으면 빈 목록")


# ---------------------------------------------------------------- state
class Brief(TypedDict):
    collected: list                             # breaking candidates (ledger removed)
    deep:      list                             # weekly candidates
    tier1:     dict                             # {"status", "item"?, "reason"?}
    meta:      dict                             # window, escalation, dead/silent/gaps
    picked:    list
    drafted:   Annotated[list, operator.add]    # report workers write in parallel
    verified:  list                             # no reducer: verify replaces it
    log:       Annotated[list, operator.add]

class ReportIn(TypedDict):
    item: dict


# ---------------------------------------------------------------- ① collect
def age_h(it, now):
    return (now - datetime.fromisoformat(it["at"])).total_seconds() / 3600

def fetch_tier1(led):
    from tier1_mou import load as mou_load, tier1_for
    try:
        by_day, err = mou_load(days=TIER1_LOOKBACK_D + 2)
    except SystemExit as exc:                   # key missing
        return {"status": "DEAD", "reason": str(exc)}
    except requests.RequestException as exc:
        return {"status": "DEAD", "reason": type(exc).__name__}
    if by_day is None:
        return {"status": "DEAD", "reason": err.get("error", "")}
    today = datetime.now(KST)
    for k in range(TIER1_LOOKBACK_D + 1):
        d = today - timedelta(days=k)
        if d.weekday() >= 5:
            continue
        day = d.strftime("%Y%m%d")
        status, pick = tier1_for(day, by_day)
        if status == "NO_PUBLICATION":          # today's may not be up yet: step back
            continue
        if status == "BELOW_BAR":               # the latest business day decides
            return {"status": status, "day": day}
        url = pick.get("url") or ""
        if url and link_key(url) in led:
            return {"status": "ALREADY_PUBLISHED", "day": day}
        at = datetime.strptime(day, "%Y%m%d").replace(tzinfo=KST)
        return {"status": "OPEN", "day": day,
                "item": {"source": "통일부", "slot": "tier1", "title": pick.get("sj") or "",
                         "url": url, "link": url, "at": at.isoformat(),
                         "body": pick.get("cn") or ""}}
    # every weekday in the lookback empty: a holiday run is possible, but so is
    # an API that answers "normal, 0 items" after a change -- keep them apart
    # from a single late day, and alert on it
    return {"status": "STALE", "reason": f"영업일 {TIER1_LOOKBACK_D}일 연속 발행 없음"}

def collect(s: dict) -> dict:
    # one fetch per feed; the ladder is applied to that single result in memory
    res = collect_feeds({"hours": DEEP_WINDOW_H})
    led = load_ledger()
    now = datetime.now(timezone.utc)
    fresh = [dict(it, url=it["link"]) for it in res["items"] if link_key(it["link"]) not in led]
    daily = [i for i in fresh if i["source"] not in WEEKLY]
    for hours in LADDER:
        breaking = [dict(i, slot="breaking") for i in daily if age_h(i, now) <= hours]
        if len(breaking) >= MIN_ITEMS:
            break
    deep = [dict(i, slot="deep") for i in fresh if i["source"] in WEEKLY]
    t1 = fetch_tier1(led)
    # collect_feeds judged "silent" over the 168h fetch, where a frozen daily
    # feed keeps its old items for a week. Judge daily sources over 24h here,
    # on everything fetched (ledger included: a published item is still a sign of life).
    # Sources switched off by NK_SKIP_SOURCES are neither silent nor counted
    # toward "every feed dead" -- otherwise the day all remaining feeds die
    # would never reach the failure notice.
    off = res.get("off", [])
    active = [s for s in SOURCES if s[0] not in off]
    dead_names = {d["source"] for d in res["dead"]}
    alive_24h = {i["source"] for i in res["items"] if age_h(i, now) <= 24}
    silent = [n for n, _u, expect in active
              if expect and n not in dead_names and n not in alive_24h]
    meta = {"window_h": hours, "escalated": hours != LADDER[0],
            "below_min": len(breaking) < MIN_ITEMS, "ledger_removed": len(res["items"]) - len(fresh),
            "dead": res["dead"], "silent": silent, "gaps": res["gaps"], "off": off,
            "all_dead": len(dead_names) == len(active),
            "seen_now": res["seen_now"]}
    log = [f"① 수집   속보 {hours}h 창 {len(breaking)}건 · 심층 {len(deep)}건 · "
           f"1차 {t1['status']} · 원장 제외 {meta['ledger_removed']}건"]
    if meta["escalated"]:
        log.append(f"   ESCALATED 24h에 {MIN_ITEMS}건 미만이라 {hours}h로 넓힘")
    if meta["below_min"]:
        log.append(f"   BELOW_MIN {LADDER[-1]}h에도 {MIN_ITEMS}건 미만 — 있는 만큼만")
    for n in off:
        log.append(f"   OFF    {n}: NK_SKIP_SOURCES로 끔")
    for d in res["dead"]:
        log.append(f"   DEAD   {d['source']}: {d['reason']}")
    for n in silent:
        log.append(f"   SILENT {n}: 응답은 정상인데 24h 안의 기사가 0")
    for g in res["gaps"]:
        log.append(f"   GAP    {g['source']} 마지막 확인 {g['last_seen']} 이후가 피드에서 빠짐")
    if t1["status"] in ("DEAD", "STALE"):
        log.append(f"   {t1['status']:<6} 통일부 API: {t1.get('reason', '')}")
    return {"collected": breaking, "deep": deep, "tier1": t1, "meta": meta, "log": log}


# ---------------------------------------------------------------- ② select
def ask_picks(items, n):
    listing = "\n".join(f"{i}. [{it['source']}] {it['title']}" for i, it in enumerate(items))
    system = (f"{CRITERIA}\n\n아래 목록에서 중요한 순서대로 최대 {n}건을 고르세요.\n"
              "버릴 것에 해당하는 기사는 수를 못 채우더라도 고르지 마세요.\n"
              "criterion에는 그 기사가 실제로 해당하는 중요도 기준 번호를 적으세요. "
              "기준에 억지로 끼워 맞추지 말고, 해당하는 기준이 없으면 0을 적으세요.\n"
              "event에는 분야가 아니라 구체적인 사건을 적고, 같은 사건을 다룬 기사에만 같은 event를 붙이세요. "
              "같은 분야라도 다른 사건이면 다른 event입니다.\n"
              "반대로 같은 훈련·발표·조치를 다른 각도로 쓴 기사(종합·분석·후속·반응)는 "
              "제목이 달라도 같은 사건이니 똑같은 event 문장을 붙이세요.")
    out = parse(system, listing, Shortlist)
    seen, picks = set(), []
    for p in out.picks:                         # no out-of-range, no repeated number
        if 0 <= p.index < len(items) and p.index not in seen:
            seen.add(p.index)
            picks.append(p)
    return picks

def ranked_both_ways(items, n):
    """One-screen ranking depends on list order: measured 2026-09-14
    (exp/step6.log), the same 12 titles listed forward and reversed shared 3
    of 5 picks and 0 of 5 ranks. Ask both orders and merge by rank points
    (n for 1st ... 1 for nth, 0 if not picked). An item both lists agree on
    beats one that a single order happened to favour.
    A criterion of 0 from either order sticks: an item one order could only
    fit by stretching is not one to publish."""
    fwd = ask_picks(items, n)
    order = list(range(len(items)))[::-1]
    rev = [p.model_copy(update={"index": order[p.index]})
           for p in ask_picks([items[i] for i in order], n)]
    points, first, none = {}, {}, set()
    for ranked in (fwd, rev):
        for rank, p in enumerate(ranked[:n]):       # the model may return more than asked
            points[p.index] = points.get(p.index, 0) + (n - rank)
            first.setdefault(p.index, p)            # keep the forward call's label when both have it
            if p.criterion == 0:
                none.add(p.index)
    merged = sorted(points, key=lambda i: (-points[i], i))
    return [first[i].model_copy(update={"criterion": 0}) if i in none else first[i] for i in merged]

def enforce(items, picks, target, banned=None):
    """The prompt asks for distinct events; the code makes sure of it.
    banned: {item index: twin link} already judged duplicates by find_dupes.
    dropped entries are (item, why, twin link or None) -- the twin decides
    later whether the dropped item may come back on a wider window."""
    banned = banned or {}
    kept, dropped, events, per_src = [], [], {}, {}
    for p in picks:
        if len(kept) == target:
            break
        it = items[p.index]
        if not 1 <= p.criterion <= len(CFG["중요도_기준"]):
            dropped.append((it, "중요도 기준 해당 없음", None))
            continue
        if p.index in banned:
            dropped.append((it, "같은 사건 (묶음 재확인)", banned[p.index]))
            continue
        ev = re.sub(r"\s+", "", p.event).lower()
        if ev in events:
            dropped.append((it, f"같은 사건 '{p.event}'", events[ev]))
            continue
        if per_src.get(it["source"], 0) >= MAX_PER_SOURCE:
            dropped.append((it, f"소스 상한 {MAX_PER_SOURCE}", None))
            continue
        events[ev] = it["link"]
        per_src[it["source"]] = per_src.get(it["source"], 0) + 1
        kept.append(dict(it, reason=p.reason, event=p.event, criterion=p.criterion,
                         rank=len(kept), _i=p.index))
    return kept, dropped


class Dupes(BaseModel):
    groups: list[list[int]] = Field(description="같은 사건을 다룬 번호끼리 묶은 목록. 짝이 없는 번호는 적지 않는다")

def find_dupes(kept):
    """Labels written one article at a time do not match across articles:
    measured 2026-09-14, the same 12 Sept strike drill came back as
    '4종 섞어쏘기 전술 사용' and '합동타격훈련 실시' and both were published.
    Asking about the short list as a whole compares them side by side."""
    if len(kept) < 2:
        return {}
    listing = "\n".join(f"{k}. [{it['source']}] {it['title']}" for k, it in enumerate(kept))
    system = ("아래 기사 가운데 같은 사건(같은 훈련·발표·조치·사고)을 다룬 기사끼리 번호를 묶으세요.\n"
              "종합·분석·후속·반응 기사도 원래 사건과 같은 묶음입니다. 같은 분야일 뿐 다른 사건이면 묶지 마세요.")
    out = parse(system, listing, Dupes)
    ban = {}
    for g in out.groups:
        g = sorted({k for k in g if 0 <= k < len(kept)})
        for k in g[1:]:                             # keep the higher-ranked one
            ban[kept[k]["_i"]] = kept[g[0]]["link"]
    return ban

def select(s: dict) -> dict:
    items, log = s["collected"], []
    if len(items) > BATCH:                      # prelim only when one screen is too long
        # equal batches, each keeping the same share. Slicing by BATCH left a
        # tail batch (44 -> 40 + 4) that kept all 4 of "top 8" without any
        # comparison: the smallest batch was the easiest way into the final.
        n_batches = math.ceil(len(items) / BATCH)
        size = math.ceil(len(items) / n_batches)
        survivors = []
        for i in range(0, len(items), size):
            chunk = items[i:i + size]
            keep = max(1, round(PRELIM * len(chunk) / BATCH))
            survivors += [chunk[p.index] for p in ask_picks(chunk, keep)[:keep]]
        log.append(f"② 선별   예선 {len(items)} → {len(survivors)}건 (묶음 {n_batches}개 × 약 {size}건)")
    else:
        survivors = items
    breaking, dropped = [], []
    if survivors:
        # ask for spares so a code-level drop does not leave the slot short
        picks = ranked_both_ways(survivors, TARGET + 3)
        banned = {}
        for _ in range(3):                      # a refill can bring in a new duplicate
            breaking, dropped = enforce(survivors, picks, TARGET, banned)
            new = {i: t for i, t in find_dupes(breaking).items() if i not in banned}
            if not new:
                break
            banned.update(new)
        else:
            breaking, dropped = enforce(survivors, picks, TARGET, banned)
            log.append("   ! 중복 재확인 3회에도 남은 중복이 있을 수 있음")
    deep = []
    if s["deep"]:
        p = ask_picks(s["deep"], 1) if len(s["deep"]) > 1 else [Pick(index=0, reason="", event="", criterion=0)]
        deep = [dict(s["deep"][p[0].index], reason=p[0].reason)] if p else []
    tier1 = [s["tier1"]["item"]] if s["tier1"].get("status") == "OPEN" else []
    picked = tier1 + breaking + deep
    log.append(f"② 선별   속보 {len(items)} → {len(breaking)} · 심층 {len(s['deep'])} → {len(deep)}"
               f" · 1차 {len(tier1)}")
    for it in breaking:                         # a drop is only readable next to what it lost to
        log.append(f"   + [{it['source']}] {it['title'][:40]} — 기준 {it['criterion']} · {it['event']}")
    for it, why, _twin in dropped:
        log.append(f"   − [{it['source']}] {it['title'][:40]} — {why}")
    # same-event drops ride along with their twin into the ledger once the twin
    # is actually sent; otherwise a 48h window tomorrow serves them as new
    twins = [{"item": it, "twin": twin} for it, _why, twin in dropped if twin]
    return {"picked": picked, "meta": {**s["meta"], "twins": twins}, "log": log}


# ---------------------------------------------------------------- ③ report
KO = re.compile(r"[가-힣]")

def extract_body(it):
    if it.get("body"):                          # tier1: the API summary is the whole text
        return it["body"]
    # requests with a real User-Agent, not trafilatura.fetch_url: 38North blocks
    # the library's default agent and fetch_url turns that into a quiet None.
    # Bytes, not r.text: a missing charset header makes r.text mojibake that
    # still has a length.
    r = requests.get(it["url"], headers=UA, timeout=20)
    r.raise_for_status()
    return trafilatura.extract(r.content) or ""

SOURCE_LANG = {"DailyNK-JP": "일본어", "AsiaPress": "일본어", "38North": "영어"}
FIELDS = ("headline", "summary", "why")

def korean_ok(d):
    return d is not None and all(KO.search(getattr(d, k)) for k in FIELDS)

def draft(body, source=""):
    """Measured 2026-09-14 (exp/step8_retry_rate.log): one DailyNK Japan body
    came back Japanese on 9 of 10 first tries with SYS_DRAFT alone, and 0 of
    10 once the user message opened by naming the source language. The
    instruction in the system prompt was already there; next to 900 chars of
    Japanese it lost. So name the language right above the text."""
    lang = SOURCE_LANG.get(source) or ("" if KO.search(body[:500]) else "외국어")
    head = f"[아래는 {lang} 기사 본문입니다. 헤드라인·요약·왜 중요한지를 모두 한국어로만 쓰세요.]\n\n" if lang else ""
    d = parse(SYS_DRAFT, head + body[:6000], Draft)
    if d is None or korean_ok(d):
        return d, 0
    return parse(SYS_DRAFT + "\n반드시 한국어로 다시 쓰세요.", head + body[:6000], Draft), 1

def fan_report(s: dict):
    return [Send("report", {"item": it}) for it in s["picked"]] or "verify"

def report(s: ReportIn) -> dict:
    it = s["item"]
    floor = 300 if it["slot"] == "tier1" else BODY_MIN
    try:
        body = extract_body(it)
    except Exception as exc:                    # one bad page must not sink the other workers
        return {"drafted": [], "log": [f"③ 취재   제외 {it['source']} · 원문 받기 실패 {type(exc).__name__}"]}
    if len(body) < floor:
        return {"drafted": [], "log": [f"③ 취재   제외 {it['source']} · 본문 {len(body)}자 < {floor} "
                                       f"· 앞부분 {body[:40]!r}"]}
    try:
        d, retried = draft(body, it["source"])
        if d is None:                           # parse() gives None on a refusal
            raise ValueError("model returned no draft")
    except Exception as exc:
        return {"drafted": [], "log": [f"③ 취재   제외 {it['source']} · 초안 실패 {type(exc).__name__}"]}
    if not korean_ok(d):                        # the retry is a second draw, not a guarantee
        bad = [k for k in FIELDS if not KO.search(getattr(d, k))]
        return {"drafted": [], "log": [f"③ 취재   제외 {it['source']} · 재요청 후에도 한글 없는 칸 {bad}"]}
    topic = d.topic if d.topic in TOPICS else ""
    return {"drafted": [{**it, "body": body[:6000], **d.model_dump(), "topic": topic}],
            "log": [f"③ 취재   {it['source']} · 본문 {len(body)}자"
                    + (" · 한국어 재요청 1회" if retried else "")
                    + ("" if topic else f" · 토픽 '{d.topic}' 목록에 없음")]}


# ---------------------------------------------------------------- ④ verify
def check(d):
    user = (f"[원문]\n{d['body'][:5000]}\n\n"
            f"[헤드라인]\n{d['headline']}\n\n[요약]\n{d['summary']}")
    return parse(SYS_CHECK, user, Verdict)

def verify(s: dict) -> dict:
    kept, log = [], []
    for d in s["drafted"]:
        try:
            v = check(d)
            if v is None:
                raise ValueError("model returned no verdict")
        except Exception as exc:                # unchecked is not passed: drop it, say why
            log.append(f"   − [{d['source']}] {d['headline'][:30]} — 검수 실패 {type(exc).__name__}")
            continue
        if v.ok:
            kept.append(d)
        else:
            log.append(f"   − [{d['source']}] {d['headline'][:30]} — {'; '.join(v.problems)[:80]}")
    return {"verified": kept,
            "log": [f"④ 검수   {len(s['drafted'])} → {len(kept)}건"] + log}


# ---------------------------------------------------------------- ⑤ publish
TITLE_MAX, DESC_MAX, EMBED_MAX, TOTAL_MAX = 256, 4096, 10, 5800
SLOT_LABEL = {"tier1": "1차", "breaking": "속보", "deep": "심층"}
SLOT_ORDER = {"tier1": 0, "breaking": 1, "deep": 2}

def color_of(topic):
    c = TOPICS.get(topic, {}).get("색")
    return int(c[1:], 16) if c else DEFAULT_COLOR

def make_lead(arts, meta):
    if not arts:
        return ""
    srcs = ", ".join(dict.fromkeys(a["source"] for a in arts))
    lead = f"오늘은 {len(arts)}건을 골랐습니다. ({srcs})"
    if meta.get("escalated"):
        lead += f"\n최근 24시간 기사가 적어 {meta['window_h']}시간 안의 기사까지 넓혀 골랐습니다."
    return lead

def is_dry():
    """Only an explicit DRY_RUN=0 sends. 'true', 'yes', a typo or nothing all
    stay dry -- the failure of a wrong value should be a missed post, not a
    real one."""
    return os.environ.get("DRY_RUN", "1").strip() != "0"

def build_embeds(run_id, lead, arts, failure=""):
    if not arts:
        # a broken pipeline must not read as a quiet news day to the reader
        text = f"⚠️ {failure} 오늘 브리핑을 만들지 못했습니다." if failure else "오늘은 실을 기사가 없습니다."
        return [{"title": f"🗞️ {run_id} · 북한 브리핑", "color": DEFAULT_COLOR,
                 "description": text}], 0
    embeds = [{"title": f"🗞️ {run_id} · 북한 브리핑", "description": lead, "color": DEFAULT_COLOR}]
    for i, a in enumerate(arts, 1):
        desc = a["summary"] + (f"\n\n💡 **{a['why']}**" if a.get("why") else "")
        card = {"title": f"{i}. [{SLOT_LABEL[a['slot']]}] {a['headline']}"[:TITLE_MAX],
                "description": desc[:DESC_MAX],
                "color": color_of(a.get("topic", "")),
                "footer": {"text": " · ".join(x for x in (a["source"], a.get("topic"), a["when"]) if x)}}
        if a.get("url"):                        # an empty url can make Discord refuse the whole post
            card["url"] = a["url"]
        embeds.append(card)
    total = lambda es: sum(len(e.get("title", "")) + len(e.get("description", ""))
                           + len(e.get("footer", {}).get("text", "")) for e in es)
    dropped = 0
    while len(embeds) > EMBED_MAX or total(embeds) > TOTAL_MAX:
        embeds.pop()
        dropped += 1
    return embeds, dropped

def send(payload, webhook, dry_run):
    if dry_run:
        print(f"[dry-run] embed {len(payload['embeds'])}개 · "
              f"{len(json.dumps(payload, ensure_ascii=False))}자 — 보내지 않음")
        for e in payload["embeds"]:
            print(f"  {e['title']}")
            print(f"    {e.get('description', '')[:160]}")
        return False
    if not webhook:
        raise RuntimeError("DRY_RUN이 0인데 DISCORD_WEBHOOK_URL이 비어 있어요")
    try:
        r = requests.post(webhook, json=payload, timeout=20)
    except requests.RequestException as exc:    # the message would carry the webhook token
        raise RuntimeError(f"발행 요청 실패: {type(exc).__name__}") from None
    if r.status_code not in (200, 204):
        raise RuntimeError(f"발행 실패 {r.status_code} {r.text[:120]}")
    return True

def fit_brief(verified):
    """Trim after verify, not at select: a deep or tier1 item that fails its
    draft or check hands its card back to the next breaking item.
    Breaking goes by the select rank -- parallel workers finish in any order."""
    special = [a for a in verified if a["slot"] != "breaking"]
    breaking = sorted((a for a in verified if a["slot"] == "breaking"), key=lambda a: a.get("rank", 0))
    size = BRIEF_MAX if len(special) >= 2 else BRIEF_SIZE
    keep = breaking[:max(0, size - len(special))]
    return sorted(special + keep, key=lambda a: SLOT_ORDER[a["slot"]]), breaking[len(keep):]

def publish(s: dict) -> dict:
    ver, spare = fit_brief(s["verified"])
    arts = [{**a, "when": datetime.fromisoformat(a["at"]).astimezone(KST).strftime("%m-%d %H:%M")
             if a["slot"] != "tier1" else datetime.fromisoformat(a["at"]).strftime("%m-%d")}
            for a in ver]
    meta = s["meta"]
    failure = ""
    if meta.get("all_dead"):
        failure = "모든 뉴스 피드 수집에 실패해"
    elif s["picked"] and not s["drafted"]:
        failure = f"고른 기사 {len(s['picked'])}건 가운데 초안까지 만든 기사가 없어"
    today = datetime.now(KST).strftime("%Y-%m-%d")
    embeds, dropped = build_embeds(today, make_lead(arts, meta), arts, failure)
    payload = {"username": "북한 브리핑", "embeds": embeds}
    sent = send(payload, os.environ.get("DISCORD_WEBHOOK_URL"), dry_run=is_dry())
    # the ledger follows the send, not the run: dropped cards and dry runs stay eligible
    shipped = ver[:len(embeds) - 1] if arts else []
    if sent and shipped:
        sent_keys = {link_key(a["link"]) for a in shipped}
        twins = [t["item"] for t in meta.get("twins", []) if link_key(t["twin"]) in sent_keys]
        mark_published(shipped + twins)
    log = [f"⑤ 발행   {len(shipped)}건 · {'보냄' if sent else 'dry-run'}"]
    for a in spare:
        log.append(f"   [예비] [{a['source']}] {a['headline'][:30]} — 칸이 차서 안 실음, 내일 후보로 남음")
    if dropped:
        log.append(f"   [한도] 카드 {dropped}장을 빼고 보냄 — 뺀 기사는 원장에 안 올라 내일 후보로 남음")
    if failure:
        log.append(f"   FAILED {failure}")
    return {"meta": {**meta, "failed": failure, "shipped": len(shipped), "spare": len(spare)}, "log": log}


# ---------------------------------------------------------------- graph
def build():
    g = StateGraph(Brief)
    for name in ("collect", "select", "report", "verify", "publish"):
        g.add_node(name, globals()[name])
    g.add_edge(START, "collect")
    g.add_edge("collect", "select")
    g.add_conditional_edges("select", fan_report, ["report", "verify"])
    g.add_edge("report", "verify")
    g.add_edge("verify", "publish")
    g.add_edge("publish", END)
    return g

INIT = {"collected": [], "deep": [], "tier1": {}, "meta": {},
        "picked": [], "drafted": [], "verified": [], "log": []}

def append_row(row):
    os.makedirs(STORE, exist_ok=True)
    with open(METRICS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

def run():
    t0 = time.time()
    try:
        out = build().compile().invoke(INIT)
    except Exception as exc:
        # a crashed run leaves a row too; the scorecard counts these. Only the
        # type and our own RuntimeError text -- other messages may carry URLs
        append_row({"kind": "graph", "ts": datetime.now(timezone.utc).isoformat(),
                    "run_id": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "dry_run": is_dry(),
                    "error": type(exc).__name__ + (f": {exc}" if isinstance(exc, RuntimeError) else ""),
                    "elapsed_s": round(time.time() - t0, 1)})
        raise
    meta = out["meta"]
    by_source, by_slot = {}, {}
    for a in out["verified"]:
        by_source[a["source"]] = by_source.get(a["source"], 0) + 1
        by_slot[a["slot"]] = by_slot.get(a["slot"], 0) + 1
    row = {"kind": "graph",
           "ts": datetime.now(timezone.utc).isoformat(),
           "run_id": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
           "dry_run": is_dry(), "failed": meta.get("failed", ""),
           "collected": len(out["collected"]), "deep": len(out["deep"]),
           "tier1": out["tier1"].get("status"),
           "picked": len(out["picked"]), "drafted": len(out["drafted"]),
           "published": len(out["verified"]),   # passed verify; the brief carries "shipped" of them
           "shipped": meta.get("shipped"), "spare": meta.get("spare"),
           "window_h": meta.get("window_h"), "escalated": meta.get("escalated"),
           "below_min": meta.get("below_min"),
           "dead": meta.get("dead"), "silent": meta.get("silent"), "gaps": meta.get("gaps"),
           "off": meta.get("off", []),
           "by_source": by_source, "by_slot": by_slot,
           "elapsed_s": round(time.time() - t0, 1), "log": out["log"]}
    append_row(row)
    # GAP detection compares against the last *published* run's sighting; a
    # local dry run advancing it would hide a gap from tomorrow's real run
    # (and conflict with the bot's commit of the same file)
    if meta.get("seen_now") and not is_dry():
        merged = load_seen()
        merged.update(meta["seen_now"])
        with open(SEEN, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=1)
    return out
