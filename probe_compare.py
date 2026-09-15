# -*- coding: utf-8 -*-
"""Can the brief put a US/UK story and a Chinese story about the same event
side by side? Two things have to be true before any design work:

  overlap  on a normal day, Chinese state outlets and US/UK outlets cover
           some of the same events inside one collection window
  pairs    for those events both bodies can be fetched, and a comparison
           written from them quotes words that are really in each text

overlap: every Chinese item of the last WINDOW_H hours is judged by the model
against the full US/UK title list (same event or not, which titles). Items
sharing a US/UK title are merged into one event. Each feed's window span is
recorded: a feed showing 3 hours cannot show a 48h overlap.

pairs: for up to PILOT events with a Chinese body and a US/UK body, the model
writes a short comparison with a verbatim quote from each side per point. The
quotes are then looked up in the bodies by code. A quote that is not there is
counted, not trusted -- this is the check a real comparison card would need.

Canaries: a US/UK title copied verbatim must match; an invented panda story
must not. Writes probe_compare.json (partial on errors). Never touches store/.
"""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Literal

import feedparser, trafilatura
from pydantic import BaseModel, Field

import graph
from probe_topics import get, plain, rss_text, when, BODY_MIN

sys.stdout.reconfigure(errors="replace")

NOW = datetime.now(timezone.utc)
WINDOW_H = 48
FUTURE_SLACK_H = 12        # ECNS stamps China time as UTC: items look 7-8h in the future
PILOT = 4
HERE = os.path.dirname(os.path.abspath(__file__))

ANGLO = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Guardian World", "https://www.theguardian.com/world/rss"),
    ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
    ("CBS World", "https://www.cbsnews.com/latest/rss/world"),
    ("ABC International", "https://abcnews.go.com/abcnews/internationalheadlines"),
    ("PBS NewsHour World", "https://www.pbs.org/newshour/feeds/rss/world"),
    ("Independent World", "https://www.independent.co.uk/news/world/rss"),
    ("Fox News World", "https://moxie.foxnews.com/google-publisher/world.xml"),
    ("The Hill International", "https://thehill.com/policy/international/feed/"),
    ("CNBC World", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
]
CHINA = [
    ("CGTN World", "https://www.cgtn.com/subscribe/rss/section/world.xml"),
    ("CGTN China", "https://www.cgtn.com/subscribe/rss/section/china.xml"),
    ("CGTN Politics", "https://www.cgtn.com/subscribe/rss/section/politics.xml"),
    ("중국신문망 국제", "https://www.chinanews.com.cn/rss/world.xml"),
    ("중국신문망 요문", "http://www.chinanews.com.cn/rss/importnews.xml"),
    ("ECNS", "https://www.ecns.cn/rss/rss.xml"),
]


def fetch(name, url):
    r, err = get(url)
    if r is None or r.status_code != 200:
        return {"name": name, "status": err or r.status_code, "items": []}
    f = feedparser.parse(r.content)
    items, ages = [], []
    for e in f.entries:
        t = when(e)
        if not t:
            continue
        age = (NOW - t).total_seconds() / 3600
        ages.append(age)
        if -FUTURE_SLACK_H <= age <= WINDOW_H:
            items.append({"source": name, "title": plain(e.get("title")), "link": e.get("link", ""),
                          "summary": rss_text(e)[:400], "age_h": round(age, 1)})
    return {"name": name, "status": 200, "entries": len(f.entries), "in_window": len(items),
            # the feed only reaches back this far: overlap beyond it is invisible
            "span_h": round(max(ages) - min(ages), 1) if len(ages) > 1 else None, "items": items}


class Candidates(BaseModel):
    event_ko: str = Field(description="이 중국 매체 기사가 다루는 구체적인 사건 하나를 한국어 한 줄로")
    candidates: list[int] = Field(description="같은 사건일 가능성이 있는 영미권 기사 번호, 최대 3개. 없으면 빈 목록")
    kind: Literal["중국 국내", "중미관계", "국제정세", "경제", "기타"]

class Pair(BaseModel):
    # the shared fact first: a pair that cannot name one is not the same event
    shared_fact_ko: str = Field(description="두 기사에 모두 적힌 같은 사실 하나(누가 무엇을 언제). 없으면 빈 문자열")
    same_event: bool = Field(description="두 기사가 같은 발표·회담·공격·사고·조치를 다루면 true")

def sys_candidates(anglo):
    return ("아래는 영미권 매체가 최근 낸 기사 제목 목록입니다.\n"
            "주어진 중국 매체 기사와 같은 사건을 다뤘을 가능성이 있는 영미권 기사 번호를 최대 3개 고르세요. "
            "그럴듯한 것이 없으면 빈 목록입니다.\n\n"
            + "\n".join(f"{i}. [{a['source']}] {a['title']}" for i, a in enumerate(anglo)))

SYS_PAIR = ("두 기사가 같은 사건(같은 발표·회담·공격·사고·조치)을 다루는지 판정하세요.\n"
            "같은 나라, 같은 분야, 같은 주제(AI·기후·중동)라는 것만으로는 같은 사건이 아닙니다.\n"
            "두 기사 모두에 적힌 구체적인 사실 하나를 댈 수 있을 때만 true입니다.")

def text_of(it):
    return f"[{it['source']}] {it['title']}\n{it['summary'] or '(요약 없음)'}"

def judge(item, system, anglo):
    """Measured 2026-09-15: one call picking matches out of 259 titles joined a
    Chengdu panda story (canary) to a real article and a Chinese medical pricing
    rule to US power-plant emissions. The long list only proposes now; each
    proposal is confirmed on its own, two texts side by side."""
    c = graph.parse(system, text_of(item), Candidates)
    if c is None:
        raise ValueError("model returned no candidates")
    bad = [i for i in c.candidates if not 0 <= i < len(anglo)]
    if bad:                                     # an index outside the list is an error, not a match
        raise ValueError(f"index out of range {bad}")
    matched, pairs = [], []
    for i in sorted(set(c.candidates))[:3]:
        p = graph.parse(SYS_PAIR, f"[기사 1]\n{text_of(item)}\n\n[기사 2]\n{text_of(anglo[i])}", Pair)
        if p is None:
            raise ValueError("model returned no pair verdict")
        ok = p.same_event and bool(p.shared_fact_ko.strip())
        pairs.append({"anglo": i, "same": ok, "fact": p.shared_fact_ko[:100]})
        if ok:
            matched.append(i)
    return {"event": c.event_ko, "kind": c.kind, "candidates": sorted(set(c.candidates)),
            "matched": matched, "pairs": pairs}


# ---------------------------------------------------------------- pilot
class Point(BaseModel):
    aspect: str = Field(description="무엇이 다른지 한국어로 짧게 (예: 책임 주체, 인용한 사람, 빠진 사실, 표현의 강도)")
    anglo_quote: str = Field(description="영미권 원문에서 그대로 옮긴 구절. 원문 언어 그대로, 20단어 이내")
    china_quote: str = Field(description="중국 매체 원문에서 그대로 옮긴 구절. 원문 언어 그대로, 20단어(중국어는 40자) 이내")
    explain_ko: str = Field(description="두 구절이 어떻게 다른지 한국어 한 문장. 구절에 없는 사실은 쓰지 않는다")

class Compare(BaseModel):
    event_ko: str = Field(description="두 기사가 함께 다루는 사건 한 줄")
    same_event: bool = Field(description="두 기사가 정말 같은 사건이면 true")
    points: list[Point] = Field(description="보도 관점이 다른 지점 2~3개. 없으면 빈 목록")

SYS_COMPARE = ("두 기사는 같은 사건을 영미권 매체와 중국 매체가 각각 보도한 것입니다.\n"
               "두 매체가 이 사건을 어떻게 다르게 전하는지 비교하세요: 누구를 주체로 쓰는지, 누구 말을 인용하는지, "
               "어떤 사실을 넣거나 빼는지, 어떤 단어를 고르는지.\n"
               "각 지점마다 양쪽 원문에서 구절을 글자 그대로 옮기세요. 번역하거나 고쳐 쓰지 마세요.\n"
               "어느 쪽이 옳다고 판정하지 말고, 차이만 보여 주세요.")

def norm(s):
    return re.sub(r"[\s\"'“”‘’「」『』]+", "", s).lower()

def body(link):
    r, err = get(link)
    if r is None or r.status_code != 200:
        return None, err or f"http {r.status_code}"
    text = (trafilatura.extract(r.content) or "").strip()
    return (text, "ok") if len(text) >= BODY_MIN else (None, f"body {len(text)}")


if __name__ == "__main__":
    graph.load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 없어 같은 사건 판정을 할 수 없습니다.")
    t0 = time.time()
    with ThreadPoolExecutor(8) as pool:
        feeds = list(pool.map(lambda s: fetch(*s), ANGLO + CHINA))
    anglo = [it for f in feeds[:len(ANGLO)] for it in f["items"]]
    china = [it for f in feeds[len(ANGLO):] for it in f["items"]]
    for f in feeds:
        print(f"{f['name']:<24}status={f['status']} entries={f.get('entries')} "
              f"{WINDOW_H}h={f.get('in_window')} span_h={f.get('span_h')}", flush=True)
    print(f"영미권 {len(anglo)}건 · 중국 {len(china)}건", flush=True)
    if not anglo or not china:
        raise SystemExit("한쪽 목록이 비어 비교할 수 없습니다")
    system = sys_candidates(anglo)

    problems = []
    canaries = [({"source": "canary", "title": anglo[0]["title"], "summary": anglo[0]["summary"]}, True),
                ({"source": "canary", "title": "Giant panda cub at Chengdu base named after public vote",
                  "summary": "Keepers at the Chengdu Research Base announced the name of a cub born in July."}, False)]
    for art, want in canaries:
        try:
            got = judge(art, system, anglo)["matched"]
        except Exception as exc:
            problems.append(f"카나리아 '{art['title'][:30]}': {type(exc).__name__}")
            continue
        if bool(got) is not want or (want and 0 not in got):
            problems.append(f"카나리아 '{art['title'][:30]}': {got} (일치 {want} 예상)")

    def safe(it):
        try:
            return {**it, **judge(it, system, anglo)}
        except Exception as exc:
            return {**it, "error": f"{type(exc).__name__}: {exc}"[:120]}
    with ThreadPoolExecutor(6) as pool:
        judged = list(pool.map(safe, china))
    errors = sum(1 for j in judged if "error" in j)

    # merge Chinese items that share a US/UK title into one event
    events = []
    for j in (j for j in judged if j.get("matched")):
        hit = next((ev for ev in events if ev["anglo_idx"] & set(j["matched"])), None)
        if hit:
            hit["anglo_idx"] |= set(j["matched"])
            hit["china"].append(j)
        else:
            events.append({"anglo_idx": set(j["matched"]), "china": [j]})
    for ev in events:
        ev["anglo"] = [anglo[i] for i in sorted(ev["anglo_idx"])]
        ev["n_outlets"] = len({a["source"] for a in ev["anglo"]}) + len({c["source"] for c in ev["china"]})
    events.sort(key=lambda ev: -ev["n_outlets"])

    pilots = []
    for ev in events:
        if len(pilots) == PILOT:
            break
        # a confirmed pair, not any two members of the merged event: merging
        # goes through shared titles and can chain two different stories
        found = None
        for c in ev["china"]:
            ctext, _why = body(c["link"])
            if not ctext:
                continue
            for i in c["matched"]:
                atext, _why = body(anglo[i]["link"])
                if atext:
                    found = (c, ctext, anglo[i], atext)
                    break
            if found:
                break
        if not found:
            pilots.append({"event": ev["china"][0]["event"], "skipped": "확인된 쌍 가운데 양쪽 본문을 다 받은 쌍이 없음"})
            continue
        c, ctext, a, atext = found
        try:
            v = graph.parse(SYS_COMPARE, f"[영미권 · {a['source']}]\n{a['title']}\n{atext[:5000]}\n\n"
                                         f"[중국 매체 · {c['source']}]\n{c['title']}\n{ctext[:5000]}", Compare)
        except Exception as exc:
            pilots.append({"event": ev["china"][0]["event"], "error": type(exc).__name__})
            errors += 1
            continue
        if v is None or not v.same_event:
            # measured 2026-09-15: asked about two different stories, the writer
            # said same_event=false and still wrote points whose quotes were real.
            # Quotes being in the text says nothing about the pair being right.
            pilots.append({"event": ev["china"][0]["event"], "skipped": "비교 단계에서 같은 사건 아님",
                           "anglo": a["title"], "china": c["title"]})
            continue
        pts = []
        for p in v.points:
            pts.append({**p.model_dump(),
                        # verbatim or not: the one part of a comparison code can check
                        "anglo_found": norm(p.anglo_quote) in norm(atext),
                        "china_found": norm(p.china_quote) in norm(ctext)})
        pilots.append({"event": v.event_ko, "same_event": v.same_event,
                       "anglo": {"source": a["source"], "title": a["title"], "link": a["link"]},
                       "china": {"source": c["source"], "title": c["title"], "link": c["link"]},
                       "points": pts})

    kinds = {}
    for j in judged:
        if j.get("matched"):
            kinds[j["kind"]] = kinds.get(j["kind"], 0) + 1
    quotes = [q for p in pilots for pt in p.get("points", []) for q in (pt["anglo_found"], pt["china_found"])]
    pair_rows = [p for j in judged for p in j.get("pairs", [])]
    summary = {"anglo_items": len(anglo), "china_items": len(china),
               "pairs_proposed": len(pair_rows), "pairs_confirmed": sum(1 for p in pair_rows if p["same"]),
               "china_matched": sum(1 for j in judged if j.get("matched")),
               "anglo_matched": len({i for j in judged for i in j.get("matched", [])}),
               "events": len(events), "matched_by_kind": kinds,
               "quotes_found": f"{sum(quotes)}/{len(quotes)}"}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    for ev in events[:15]:
        print(f"- {ev['china'][0]['event'][:60]} · 매체 {ev['n_outlets']} · "
              f"{sorted({c['source'] for c in ev['china']})} / {sorted({a['source'] for a in ev['anglo']})}")

    for p in pilots:
        print(f"\n[시험 비교] {p['event'][:70]}" + (f" — 건너뜀: {p['skipped']}" if "skipped" in p else ""))
        for pt in p.get("points", []):
            print(f"  · {pt['aspect']}: 영미 {'O' if pt['anglo_found'] else 'X'} / 중국 {'O' if pt['china_found'] else 'X'} — {pt['explain_ko'][:90]}")

    # feed summaries are publisher text: kept in memory for judging, not in
    # the tracked evidence file (the same reason exp/bodies.json is not tracked)
    for ev in events:
        ev["anglo_idx"] = sorted(ev["anglo_idx"])
        for it in ev["anglo"] + ev["china"]:
            it.pop("summary", None)
    for j in judged:
        j.pop("summary", None)
    out = "probe_compare.json" if not errors and not problems else "probe_compare.partial.json"
    with open(os.path.join(HERE, out), "w", encoding="utf-8") as fh:
        json.dump({"measured_at": NOW.isoformat(), "window_h": WINDOW_H, "summary": summary,
                   "problems": problems, "errors": errors,
                   "feeds": [{k: v for k, v in f.items() if k != "items"} for f in feeds],
                   "events": events, "unmatched_china": [j for j in judged if not j.get("matched")],
                   "pilots": pilots, "elapsed_s": round(time.time() - t0, 1)},
                  fh, ensure_ascii=False, indent=1)
    print(f"-> {out} ({time.time() - t0:.0f}s) · 오류 {errors}건")
    for p in problems:
        print("!!", p)
    if errors or problems:
        raise SystemExit("카나리아 불일치 또는 판정 오류")
