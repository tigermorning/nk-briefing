# -*- coding: utf-8 -*-
"""Are the 21 foreign candidates worth collecting? One table, same yardstick
as the core sources, plus the question the earlier probe never asked:

  does an article tell the reader something the core Korean feeds did not?

Per source:
  feed      http status, entries
  nk        entries mentioning North Korea in that language, share of feed
  24h / 7d  NK entries inside each window
  G1        up to 3 NK articles: extracted length AND the first 60 chars,
            because a length pass has been menus (NHK) and mojibake before
  kcna      of those, how many open by citing KCNA / Rodong
  novel     NK articles from the last 72h, each judged by the model against
            every core title of the last 96h: same event already covered, or new

Writes probe_sources.json. Needs OPENAI_API_KEY (graph.load_env) for `novel`.
"""
import json, re, sys, time
from datetime import datetime, timezone, timedelta

import feedparser, requests, trafilatura
from pydantic import BaseModel, Field

import graph

sys.stdout.reconfigure(errors="replace")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
NOW = datetime.now(timezone.utc)

KW = {"ko": ["북한", "北", "김정은", "평양", "조선"],
      "ja": ["北朝鮮", "金正恩", "平壌", "朝鮮民主主義"],
      "ru": ["КНДР", "Северной Кореи", "Северная Корея", "Северную Корею", "Пхеньян", "Ким Чен"],
      "en": ["North Korea", "DPRK", "Pyongyang", "Kim Jong"],
      "zh": ["朝鲜", "朝鮮", "平壤", "金正恩"]}
KCNA = re.compile(r"Korean Central News Agency|KCNA|Rodong Sinmun|朝中社|朝鲜中央通讯社|朝鮮中央通信|"
                  r"労働新聞|ЦТАК|Центральное телеграфное агентство Кореи|조선중앙통신|노동신문", re.I)

CORE = [  # group, name, lang, url
    ("핵심", "Yonhap-NK", "ko", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("핵심", "DailyNK", "ko", "https://www.dailynk.com/feed"),
    ("핵심", "RFA-KO", "ko", "https://www.rfa.org/korean/rss2.xml"),
]
CANDIDATES = [
    ("종합 국제면", "NHK 국제", "ja", "https://www.nhk.or.jp/rss/news/cat6.xml"),
    ("종합 국제면", "중국신문망 국제", "zh", "https://www.chinanews.com.cn/rss/world.xml"),
    ("종합 국제면", "시나 국제", "zh", "http://rss.sina.com.cn/news/world/focus15.xml"),
    ("종합 국제면", "신화망 세계", "zh", "http://www.xinhuanet.com/world/news_world.xml"),
    ("종합 국제면", "TASS 영문", "en", "https://tass.com/rss/v2.xml"),
    ("종합 국제면", "TASS 러시아어", "ru", "https://tass.ru/rss/v2.xml"),
    ("종합 국제면", "인테르팍스", "ru", "https://www.interfax.ru/rss.asp"),
    ("종합 국제면", "RIA 노보스티", "ru", "https://ria.ru/export/rss2/index.xml"),
    ("종합 국제면", "레그눔", "ru", "https://regnum.ru/rss"),
    ("종합 국제면", "로시스카야가제타", "ru", "https://rg.ru/xml/index.xml"),
    ("종합 국제면", "이스트러시아", "ru", "https://www.eastrussia.ru/rss/"),
    ("종합 국제면", "보스토크투데이", "ru", "https://vostok.today/rss.xml"),
    ("종합 국제면", "VOA 영문", "en", "https://www.voanews.com/api/zq$omekvi_"),
    ("종합 국제면", "RFA 영문", "en", "https://www.rfa.org/english/rss2.xml"),
    ("북한 전문", "데일리NK재팬", "ja", "https://dailynk.jp/feed"),
    ("북한 전문", "아시아프레스", "ja", "https://www.asiapress.org/apn/feed/index.xml"),
    ("북한 전문", "NK News", "en", "https://www.nknews.org/feed/"),
    ("연구소", "38North", "en", "https://www.38north.org/feed/"),
    ("연구소", "CSIS 비욘드 패럴렐", "en", "https://beyondparallel.csis.org/feed/"),
    ("연구소", "발다이클럽", "ru", "https://ru.valdaiclub.com/rss/feed.txt"),
    ("연구소", "IDE-JETRO", "ja", "https://www.ide.go.jp/rss/japanese.xml"),
]


def age_h(e):
    t = e.get("published_parsed") or e.get("updated_parsed")
    return None if not t else (NOW - datetime(*t[:6], tzinfo=timezone.utc)).total_seconds() / 3600

def text_of(e):
    return re.sub(r"<[^>]+>", "", (e.get("title", "") + " " + e.get("summary", "")))

def body_of(url):
    try:
        r = requests.get(url, headers=UA, timeout=25)
    except requests.RequestException as exc:
        return None, f"ERR {type(exc).__name__}"
    if r.status_code != 200:
        return None, f"http {r.status_code}"
    return trafilatura.extract(r.content) or "", "ok"

def measure(group, name, lang, url):
    row = {"group": group, "name": name, "lang": lang, "url": url}
    try:
        r = requests.get(url, headers=UA, timeout=25)
        row["http"] = r.status_code
        f = feedparser.parse(r.content)
    except requests.RequestException as exc:
        row.update(http=f"ERR {type(exc).__name__}", entries=0, nk=0)
        return row, []
    row["entries"] = len(f.entries)
    nk = [e for e in f.entries if lang == "ko" or any(k in text_of(e) for k in KW[lang])]
    ages = [age_h(e) for e in nk]
    row.update(nk=len(nk), h24=sum(1 for a in ages if a is not None and a <= 24),
               d7=sum(1 for a in ages if a is not None and a <= 168),
               newest_h=round(min((a for a in ages if a is not None), default=-1), 1))
    g1 = []
    for e in nk[:3]:
        body, status = body_of(e.get("link", ""))
        g1.append({"len": len(body or ""), "status": status,
                   "head": re.sub(r"\s+", " ", (body or ""))[:60],
                   "kcna": bool(body and KCNA.search(body[:300]))})
    row["g1"] = g1
    recent = [{"title": e.get("title", ""), "summary": re.sub(r"<[^>]+>", "", e.get("summary", ""))[:400],
               "link": e.get("link", "")} for e, a in zip(nk, ages) if a is not None and a <= 72]
    return row, recent


class Novelty(BaseModel):
    same_event_in_core: bool = Field(description="한국어 목록에 같은 사건을 다룬 기사가 있으면 true")
    matched_title: str = Field(description="같은 사건인 한국어 기사 제목. 없으면 빈 문자열")
    topic_ko: str = Field(description="이 외국 기사가 다루는 사건을 한국어 한 줄로")

def judge(article, core_titles):
    system = ("아래는 한국 매체들이 최근 96시간 동안 낸 북한 기사 제목 목록입니다.\n"
              "주어진 외국 기사가 이 목록의 어떤 기사와 같은 사건(같은 발표·훈련·조치·사고)을 다루는지 판정하세요.\n"
              "같은 분야일 뿐 다른 사건이면 false입니다.\n\n" + "\n".join(f"- {t}" for t in core_titles))
    return graph.parse(system, f"제목: {article['title']}\n요약: {article['summary']}", Novelty)


if __name__ == "__main__":
    graph.load_env()
    t0 = time.time()
    rows = []
    for spec in CORE + CANDIDATES:
        row, recent = measure(*spec)
        row["_recent"] = recent
        rows.append(row)
        print(f"{row['name']:<14} http={row.get('http')} entries={row.get('entries')} nk={row.get('nk')} "
              f"24h={row.get('h24')} 7d={row.get('d7')}", flush=True)

    # core window for the comparison: 96h, so a foreign piece written a day
    # after the Korean report still finds its match
    core_titles = []
    for g, n, lang, u in CORE:
        f = feedparser.parse(requests.get(u, headers=UA, timeout=25).content)
        core_titles += [e.get("title", "") for e in f.entries if (age_h(e) or 1e9) <= 96]
    print(f"\ncore titles in 96h: {len(core_titles)}", flush=True)

    for row in rows:
        if row["group"] == "핵심":
            row.pop("_recent")
            continue
        verdicts = []
        for a in row.pop("_recent")[:8]:
            try:
                v = judge(a, core_titles)
                verdicts.append({"title": a["title"][:80], "covered": v.same_event_in_core,
                                 "matched": v.matched_title[:60], "topic": v.topic_ko[:80]})
            except Exception as exc:
                verdicts.append({"title": a["title"][:80], "error": type(exc).__name__})
        row["novelty"] = verdicts
        new = sum(1 for v in verdicts if v.get("covered") is False)
        print(f"{row['name']:<14} 72h NK {len(verdicts)} · new {new}", flush=True)

    with open("probe_sources.json", "w", encoding="utf-8") as fh:
        json.dump({"measured_at": NOW.isoformat(), "core_titles_96h": len(core_titles),
                   "rows": rows, "elapsed_s": round(time.time() - t0, 1)}, fh, ensure_ascii=False, indent=1)
    print(f"-> probe_sources.json ({time.time() - t0:.0f}s)")
