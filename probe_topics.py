# -*- coding: utf-8 -*-
"""P0 of docs/PLAN-email-edition.md: which feeds can carry the four new
briefings (미국경제 · 중국경제 · 중미관계 · 국제정세)?

Per feed, the yardsticks the North Korea sources went through, plus fit:
  feed    http status first; a non-200 answer is never parsed
  G2      dated entries, the time span the feed window covers, rate per day,
          24h and 14d counts. 14d is only a lower bound when the window is
          shorter than 14 days -- the window is time, not a number of items
  G1      newest N articles with the production UA and trafilatura on bytes,
          one of FETCH_ERR / FETCH_HTTP / EXTRACT_EMPTY / SHORT / PASS
  teaser  spread and mid-sentence cut over those extracts (test_g1_paywall):
          both at once = TEASER. A length pass alone let NK News through
  G3      robots.txt fetched with our UA: parsed only on 200, 404/410 means
          no file, any other answer stays UNKNOWN instead of "allowed"
  fit     newest articles judged by the model against the draft criteria of
          all four briefings at once, so one feed serving two shows up too

Control feeds with a known answer run through the same code, and three
made-up articles with a known fit go through the judge. If either comes out
wrong the table is not trusted and the run exits non-zero.

Writes probe_topics.json (probe_topics.partial.json when a judgement failed).
Never touches store/. Needs OPENAI_API_KEY.
"""
import json, math, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import feedparser, requests, trafilatura
from pydantic import BaseModel, Field

import graph
from collect_nk import UA, get_once_more       # the agent and retry the pipeline will actually use
from test_g1_paywall import ENDERS, prose_end

sys.stdout.reconfigure(errors="replace")

NOW = datetime.now(timezone.utc)
N_G1 = 5
N_FIT = 12
FIT_MAX_AGE_D = 7
BODY_MIN = graph.BODY_MIN
HERE = os.path.dirname(os.path.abspath(__file__))

TOPICS = {
    "미국경제": [
        "연준이 금리·양적긴축 같은 통화정책을 결정했거나 의장·이사가 공식 발언을 했나",
        "미국 정부 기관이 고용·물가·GDP·소매판매 같은 공식 경제지표를 발표했나",
        "미국 정부·의회가 재정·세제·관세·산업정책 조치를 발표하거나 시행했나",
        "미국 국채금리·주가지수·달러가 크게 움직였고 그 원인이 보도됐나",
    ],
    "중국경제": [
        "인민은행·국무원이 금리·지준율·부양책 같은 정책을 발표했나",
        "중국 정부가 GDP·물가·PMI·수출입 같은 공식 경제지표를 발표했나",
        "중국 부동산·지방정부 부채·대기업의 위기나 구조조정에 새로 확인된 사실이 있나",
        "중국이 산업·수출통제·외국기업 규제 조치를 발표하거나 시행했나",
    ],
    "중미관계": [
        "미국과 중국 정부 사이에 회담·통화·협상이 실제로 있었나",
        "미국 또는 중국이 상대국을 겨냥한 관세·수출통제·제재·투자제한을 발표했나",
        "대만·남중국해를 둘러싸고 미국 또는 중국의 군사·외교 행동이 있었나",
        "한쪽의 조치에 다른 쪽 정부가 공식적으로 대응했나",
    ],
    "국제정세": [
        "전쟁·무력충돌에서 공격·휴전·점령 같은 실제 전개가 있었나",
        "정상회담·국제기구 결의·조약 체결이 실제로 있었나",
        "주요국에서 선거 결과·정권 교체·쿠데타가 확인됐나",
        "대규모 재해·테러·난민 사태가 일어나 국제적 대응이 있었나",
    ],
}
DISCARD = [
    "새로 일어난 일 없이 전망·가능성 분석만 있는 기사",
    "개별 종목·기업 실적·일일 시황만 다루고 거시경제나 정책과 무관한 기사",
    "해마다 같은 날 반복되는 의례·기념 행사 보도",
    "칼럼·사설·인터뷰처럼 사실 보도가 아닌 글",
]

# (group, name, lang, feed). group is only the briefing we are hoping for;
# fit is judged against all four regardless.
CONTROLS = [                                   # known from HANDOFF "소스 편성"
    ("대조", "Yonhap-NK", "ko", "https://www.yna.co.kr/rss/northkorea.xml"),
    ("대조", "38North", "en", "https://www.38north.org/feed/"),
    ("대조", "NK News", "en", "https://www.nknews.org/feed/"),
]
CONTROL_EXPECT = {"Yonhap-NK": {"g1": "PASS", "teaser": False},
                  "38North": {"g1": "PASS", "teaser": False},
                  "NK News": {"teaser": True}}
CANDIDATES = [
    ("한국어", "연합 경제", "ko", "https://www.yna.co.kr/rss/economy.xml"),
    ("한국어", "연합 국제", "ko", "https://www.yna.co.kr/rss/international.xml"),
    ("한국어", "연합 마켓", "ko", "https://www.yna.co.kr/rss/market.xml"),
    ("한국어", "한경 국제", "ko", "https://www.hankyung.com/feed/international"),
    ("한국어", "한경 경제", "ko", "https://www.hankyung.com/feed/economy"),
    ("한국어", "매경 국제", "ko", "https://www.mk.co.kr/rss/30300018/"),
    ("한국어", "경향 국제", "ko", "https://www.khan.co.kr/rss/rssdata/kh_world.xml"),
    ("한국어", "한겨레 국제", "ko", "https://www.hani.co.kr/rss/international/"),
    ("한국어", "뉴시스 국제", "ko", "https://newsis.com/RSS/international.xml"),
    ("한국어", "BBC 코리아", "ko", "https://feeds.bbci.co.uk/korean/rss.xml"),
    ("한국어", "연합인포맥스", "ko", "https://news.einfomax.co.kr/rss/allArticle.xml"),
    ("한국어", "조선 국제", "ko", "https://www.chosun.com/arc/outboundfeeds/rss/category/international/?outputType=xml"),
    ("한국어", "조선비즈 국제", "ko", "https://biz.chosun.com/arc/outboundfeeds/rss/category/international/?outputType=xml"),
    ("한국어", "서울경제 국제", "ko", "https://www.sedaily.com/rss/international"),
    ("한국어", "동아 국제", "ko", "https://rss.donga.com/international.xml"),
    ("미국경제", "CNBC Economy", "en", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("미국경제", "WSJ Economy", "en", "https://feeds.a.dj.com/rss/RSSEconomy.xml"),
    ("미국경제", "MarketWatch", "en", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("미국경제", "Bloomberg Economics", "en", "https://feeds.bloomberg.com/economics/news.rss"),
    ("미국경제", "Fed 통화정책", "en", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("미국경제", "Fed 전체", "en", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("미국경제", "BLS", "en", "https://www.bls.gov/feed/bls_latest.rss"),
    ("미국경제", "BEA", "en", "https://apps.bea.gov/rss/rss.xml"),
    ("미국경제", "NPR Economy", "en", "https://feeds.npr.org/1017/rss.xml"),
    ("미국경제", "Guardian Economics", "en", "https://www.theguardian.com/business/economics/rss"),
    ("미국경제", "Calculated Risk", "en", "https://feeds.feedburner.com/CalculatedRisk"),
    ("미국경제", "Fed 연설", "en", "https://www.federalreserve.gov/feeds/speeches.xml"),
    ("미국경제", "CNBC Finance", "en", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("미국경제", "NYT Economy", "en", "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"),
    ("미국경제", "Yahoo Finance", "en", "https://finance.yahoo.com/news/rssindex"),
    ("미국경제", "Axios", "en", "https://api.axios.com/feed/"),
    ("중국경제", "SCMP China Economy", "en", "https://www.scmp.com/rss/318421/feed"),
    ("중국경제", "SCMP Business", "en", "https://www.scmp.com/rss/92/feed"),
    # first run 2026-09-15: China Daily bizchina_rss 404, China Briefing and
    # Brookings /feed/ 200 with an HTML page and 0 entries -- replaced below
    ("중국경제", "Global Times", "en", "https://www.globaltimes.cn/rss/outbrain.xml"),
    ("중국경제", "Xinhua Business", "en", "https://english.news.cn/rss/businessrss.xml"),
    ("중국경제", "CGTN Business", "en", "https://www.cgtn.com/subscribe/rss/section/business.xml"),
    ("중국경제", "Economist Finance", "en", "https://www.economist.com/finance-and-economics/rss.xml"),
    ("중국경제", "중국신문망 재경", "zh", "https://www.chinanews.com.cn/rss/finance.xml"),
    ("중국경제", "Nikkei Asia", "en", "https://asia.nikkei.com/rss/feed/nar"),
    ("중미관계", "SCMP China", "en", "https://www.scmp.com/rss/4/feed"),
    ("중미관계", "The Diplomat", "en", "https://thediplomat.com/feed/"),
    ("중미관계", "PIIE", "en", "https://www.piie.com/rss/update.xml"),
    ("중미관계", "ChinaTalk", "en", "https://www.chinatalk.media/feed"),
    ("중미관계", "Sinocism", "en", "https://sinocism.com/feed"),
    ("국제정세", "BBC World", "en", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("국제정세", "Al Jazeera", "en", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("국제정세", "Guardian World", "en", "https://www.theguardian.com/world/rss"),
    ("국제정세", "NYT World", "en", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("국제정세", "DW World", "en", "https://rss.dw.com/rdf/rss-en-world"),
    ("국제정세", "France24", "en", "https://www.france24.com/en/rss"),
    ("국제정세", "RFI English", "en", "https://www.rfi.fr/en/rss"),
    ("국제정세", "NPR World", "en", "https://feeds.npr.org/1004/rss.xml"),
    ("국제정세", "UN News", "en", "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
    ("국제정세", "Foreign Policy", "en", "https://foreignpolicy.com/feed/"),
    ("국제정세", "War on the Rocks", "en", "https://warontherocks.com/feed/"),
    ("국제정세", "CNBC World", "en", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    # second round 2026-09-15: the reader wants 국제정세 from US/UK outlets, and
    # a side-by-side of how US/UK and Chinese outlets tell the same event.
    # Checked before listing: CNN edition_world (newest item 3 years old), VOA
    # English (1.5 years), People's Daily English (1.3 years), Xinhua English
    # (8 years), Global Times (403 or 404 on every section tried), China Daily (404).
    ("영미권", "CBS World", "en", "https://www.cbsnews.com/latest/rss/world"),
    ("영미권", "ABC International", "en", "https://abcnews.go.com/abcnews/internationalheadlines"),
    ("영미권", "PBS NewsHour World", "en", "https://www.pbs.org/newshour/feeds/rss/world"),
    ("영미권", "Sky News World", "en", "https://feeds.skynews.com/feeds/rss/world.xml"),
    ("영미권", "Independent World", "en", "https://www.independent.co.uk/news/world/rss"),
    ("영미권", "Washington Post World", "en", "https://feeds.washingtonpost.com/rss/world"),
    ("영미권", "The Hill International", "en", "https://thehill.com/policy/international/feed/"),
    ("영미권", "Fox News World", "en", "https://moxie.foxnews.com/google-publisher/world.xml"),
    ("영미권", "TIME", "en", "https://time.com/feed/"),
    ("중국매체", "CGTN World", "en", "https://www.cgtn.com/subscribe/rss/section/world.xml"),
    ("중국매체", "CGTN China", "en", "https://www.cgtn.com/subscribe/rss/section/china.xml"),
    ("중국매체", "CGTN Politics", "en", "https://www.cgtn.com/subscribe/rss/section/politics.xml"),
    ("중국매체", "중국신문망 국제", "zh", "https://www.chinanews.com.cn/rss/world.xml"),
    ("중국매체", "중국신문망 요문", "zh", "http://www.chinanews.com.cn/rss/importnews.xml"),
    ("중국매체", "ECNS", "en", "https://www.ecns.cn/rss/rss.xml"),
]


# ---------------------------------------------------------------- measure
def when(e):
    """published first, then updated/created: a feed dating items with
    <updated> is not a feed of undated items (test_g2.when)."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        t = e.get(field)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None

def plain(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()

def rss_text(e):
    if e.get("content"):
        return plain(e["content"][0].get("value"))
    return plain(e.get("summary"))

def get(url):
    """(response, None) or (None, reason), with the pipeline's one retry on a
    connection error or timeout (collect_nk.get_once_more). The first rounds
    on 2026-09-15 ran without it; the access round that evening lost the
    Yonhap-NK control to a ConnectionError twice, a failure the daily run
    retries past -- measure what the pipeline would see."""
    try:
        return get_once_more(url, headers=UA, timeout=25), None
    except requests.RequestException as exc:
        return None, type(exc).__name__

def g1_article(link):
    r, err = get(link)
    if r is None:
        return {"verdict": f"FETCH_ERR", "why": err, "len": 0}
    if r.status_code != 200:
        return {"verdict": "FETCH_HTTP", "why": str(r.status_code), "len": 0}
    text = (trafilatura.extract(r.content) or "").strip()
    if not text:
        return {"verdict": "EXTRACT_EMPTY", "why": "200 but nothing extracted", "len": 0}
    # prose_end drops byline lines holding "@"; Cloudflare-protected pages turn
    # the address into "[email protected]" and the byline stayed as the last
    # line, so every Newsis article read as cut mid-sentence (2026-09-15)
    prose = prose_end("\n".join(l for l in text.split("\n") if "email protected" not in l))
    return {"verdict": "PASS" if len(text) >= BODY_MIN else "SHORT", "len": len(text),
            "head": text[:60].replace("\n", " "), "cut": bool(prose) and prose[-1] not in ENDERS}

def teaser_of(arts):
    """Uniform length AND prose that stops mid-sentence, as in test_g1_paywall,
    but "uniform" is no longer max/min. Measured 2026-09-15: NK News served
    four teasers at 1175-1236 chars and one opinion note at 631, so max/min
    was 1.96 and the known teaser site passed as full text. One odd item must
    not decide it: all but one length within 20% of the median."""
    lens = sorted(a["len"] for a in arts if a["len"])
    if len(lens) < 3:                          # two lengths say nothing about spread
        return {"teaser": None, "teaser_n": len(lens)}
    cut = sum(1 for a in arts if a.get("cut"))
    median = lens[len(lens) // 2]
    near = sum(1 for n in lens if abs(n - median) <= 0.2 * median)
    # a feed that already carries about as much text as the page gave us is
    # not hiding a body behind a wall, whatever the lengths look like
    full_in_feed = sum(1 for a in arts if a["len"] and a["rss_len"] >= 0.8 * a["len"])
    return {"teaser": (near >= len(lens) - 1 and cut >= len(lens) - 1
                       and full_in_feed < len(lens) - 1),
            "teaser_n": len(lens), "spread": round(max(lens) / min(lens), 2),
            "near_median": near, "cut": cut, "full_in_feed": full_in_feed}

def g3(feed_url, links):
    parts = urlsplit(links[0] if links else feed_url)
    r, err = get(f"{parts.scheme}://{parts.netloc}/robots.txt")
    if r is None:
        return {"verdict": "UNKNOWN", "why": err}
    if r.status_code in (404, 410):
        return {"verdict": "NO_ROBOTS", "why": str(r.status_code)}
    if r.status_code != 200:
        # a 403 or an HTML error page parsed as rules would read as "allow all"
        return {"verdict": "UNKNOWN", "why": f"http {r.status_code}"}
    rp = RobotFileParser()
    rp.parse(r.content.decode("utf-8", "replace").splitlines())
    ok = [rp.can_fetch(UA["User-Agent"], u) for u in links]
    if not ok:
        return {"verdict": "UNKNOWN", "why": "no article link to check"}
    return {"verdict": "ALLOWED" if all(ok) else "DISALLOWED", "allowed": f"{sum(ok)}/{len(ok)}"}

def measure(group, name, lang, url):
    row = {"group": group, "name": name, "lang": lang, "url": url}
    r, err = get(url)
    if r is None:
        return {**row, "feed": "FEED_ERR", "why": err}, []
    row["http"] = r.status_code
    if r.status_code != 200:
        return {**row, "feed": "FEED_HTTP", "why": str(r.status_code)}, []
    f = feedparser.parse(r.content)
    if not f.entries:
        # 200 with no entries: an HTML page, a moved feed or a real empty one
        return {**row, "feed": "FEED_EMPTY", "why": (r.headers.get("content-type") or "")[:40]}, []
    row["feed"] = "OK"

    dated = sorted(((when(e), e) for e in f.entries if when(e)), key=lambda x: x[0], reverse=True)
    ages = [(NOW - t).total_seconds() / 3600 for t, _e in dated]
    span_h = (ages[-1] - ages[0]) if len(ages) > 1 else 0
    row["g2"] = {"entries": len(f.entries), "nodate": len(f.entries) - len(dated),
                 "h24": sum(1 for a in ages if a <= 24), "d14": sum(1 for a in ages if a <= 336),
                 "oldest_h": round(ages[-1], 1) if ages else None,
                 "newest_h": round(ages[0], 1) if ages else None,
                 "per_day": round(len(ages) / (span_h / 24), 1) if span_h > 0 else None,
                 # the window ends before 14 days: d14 is what the feed shows, not what was published
                 "window_short": bool(ages) and ages[-1] < 336}

    newest = [e for _t, e in dated] or list(f.entries)
    arts = []
    for e in newest[:N_G1]:
        a = g1_article(e.get("link", ""))
        a["rss_len"] = len(rss_text(e))
        arts.append(a)
    row["g1"] = {"pass": sum(1 for a in arts if a["verdict"] == "PASS"), "n": len(arts),
                 "verdicts": [a["verdict"] for a in arts],
                 # the feed carries the text and we extracted nothing: our side, not theirs
                 "extractor_suspect": any(a["verdict"] == "EXTRACT_EMPTY" and a["rss_len"] >= BODY_MIN for a in arts),
                 "articles": arts, **teaser_of(arts)}
    row["g3"] = g3(url, [e.get("link", "") for e in newest[:3] if e.get("link")])

    # spread the sample over the last 24h (7 days if 24h is short) instead of
    # the newest N: on a feed of 200 a day the newest 8 are one hour of
    # whatever desk happened to publish then
    for hours in (24, FIT_MAX_AGE_D * 24):
        pool_ = [e for t, e in dated if 0 <= (NOW - t).total_seconds() <= hours * 3600]
        if len(pool_) >= N_FIT:
            break
    step = max(1, len(pool_) / N_FIT)
    sample = [pool_[int(i * step)] for i in range(min(N_FIT, len(pool_)))]
    row["fit_window_h"] = hours
    recent = [{"title": plain(e.get("title")), "summary": rss_text(e)[:500], "link": e.get("link", "")}
              for e in sample]
    return row, recent


# ---------------------------------------------------------------- fit
Briefing = Literal["미국경제", "중국경제", "중미관계", "국제정세"]
assert set(Briefing.__args__) == set(TOPICS)

class Fit(BaseModel):
    # the event first, so the matches follow from what the article says
    event_ko: str = Field(description="이 기사가 다루는 구체적인 사건 하나를 한국어 한 줄로")
    # an enum, not free text: measured 2026-09-15, list[str] came back 9 of
    # ~300 times holding the criterion sentence instead of the briefing name
    matches: list[Briefing] = Field(description="중요도 기준 가운데 하나라도 '예'인 브리핑 이름. 없으면 빈 목록")
    # first run: off-topic items came back discard=true too (a concert tour,
    # a Japanese tax cut), so the column counted two different things
    discard: bool = Field(description="[버릴 것] 목록의 한 줄에 해당할 때만 true. "
                                      "어느 브리핑에도 안 맞는다는 이유만으로는 false")

SYS_FIT = ("아래 네 브리핑의 중요도 기준을 보고, 주어진 기사가 어느 브리핑에 실릴 만한지 판정하세요.\n"
           "기준 질문 가운데 하나에 기사 내용만으로 '예'라고 답할 수 있을 때만 그 브리핑을 고르세요. "
           "같은 분야라는 이유만으로 고르지 마세요. 여러 개일 수 있고 없으면 빈 목록입니다.\n\n"
           + "\n\n".join(f"[{n}]\n" + "\n".join(f"- {c}" for c in cs) for n, cs in TOPICS.items())
           + "\n\n[버릴 것]\n" + "\n".join(f"- {d}" for d in DISCARD))

def judge(a):
    v = graph.parse(SYS_FIT, f"제목: {a['title']}\n요약: {a['summary'] or '(피드에 요약 없음)'}", Fit)
    if v is None:
        raise ValueError("model returned no verdict")
    unknown = [m for m in v.matches if m not in TOPICS]
    if unknown:                                # a name outside the list is not a match, and not silence either
        raise ValueError(f"unknown briefing {unknown}")
    return {"title": a["title"][:90], "event": v.event_ko[:90], "matches": v.matches,
            "discard": v.discard, "no_summary": not a["summary"]}

CANARIES = [
    ({"title": "Fed raises benchmark rate by a quarter point, signals one more hike",
      "summary": "The Federal Reserve on Wednesday lifted its policy rate by 25 basis points, "
                 "Chair said at a press conference after the two-day meeting."}, {"미국경제"}),
    ({"title": "US adds 140 Chinese firms to export blacklist; Beijing vows countermeasures",
      "summary": "The Commerce Department placed the companies on the entity list over advanced chips. "
                 "China's commerce ministry said it would respond firmly."}, {"중미관계"}),
    ({"title": "Arsenal beat Chelsea 2-1 with late header",
      "summary": "A stoppage-time goal settled the Premier League match on Sunday."}, set()),
]


# ---------------------------------------------------------------- main
def fit_summary(verdicts):
    ok = [v for v in verdicts if "error" not in v]
    out = {"judged": len(ok), "discard": sum(1 for v in ok if v["discard"]),
           "no_summary": sum(1 for v in ok if v["no_summary"])}
    for n in TOPICS:
        out[n] = sum(1 for v in ok if n in v["matches"] and not v["discard"])
    return out

if __name__ == "__main__":
    graph.load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 없어 주제 적합도를 판정할 수 없습니다. .env를 채우세요.")
    t0 = time.time()
    # --group=a,b --tag=name measures only those groups (controls always run)
    # and writes probe_topics.<name>.json, so a follow-up round does not
    # overwrite the numbers docs/P0-sources.md already quotes. The tag is
    # ASCII: a Korean group name in a tracked file name gets quoted by git.
    arg = lambda k: next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith(f"--{k}=")), None)
    only = arg("group").split(",") if arg("group") else None
    tag = arg("tag")
    if only:
        unknown = set(only) - {g for g, *_ in CANDIDATES}
        if unknown:                            # a typo would measure nothing and say nothing
            raise SystemExit(f"없는 그룹: {sorted(unknown)}")
        if not tag or not re.fullmatch(r"[a-z0-9-]+", tag):
            raise SystemExit("--group에는 --tag=영문소문자-숫자 가 필요합니다 (출력 파일 이름)")
    specs = CONTROLS + [s for s in CANDIDATES if not only or s[0] in only]

    # one worker per host, feeds of the same host one after another. Measured
    # 2026-09-15: four Yonhap feeds fetched at once all ended in ConnectionError,
    # and the same four one by one all answered 200.
    hosts = {}
    for s in specs:
        hosts.setdefault(urlsplit(s[3]).netloc, []).append(s)
    with ThreadPoolExecutor(8) as pool:
        by_host = list(pool.map(lambda group: [measure(*s) for s in group], hosts.values()))
    done = {row["name"]: (row, recent) for group in by_host for row, recent in group}
    measured = [done[s[1]] for s in specs]
    rows = []
    for row, recent in measured:
        row["_recent"] = recent
        rows.append(row)
        g1 = row.get("g1", {})
        print(f"{row['name']:<22}{row['feed']:<11}G1 {g1.get('pass', '-')}/{g1.get('n', '-')} "
              f"teaser={g1.get('teaser')} G3={row.get('g3', {}).get('verdict', '-')}", flush=True)

    problems = []
    for row in rows:
        want = CONTROL_EXPECT.get(row["name"]) if row["group"] == "대조" else None
        if not want:
            continue
        g1 = row.get("g1", {})
        if "g1" in want and not (g1.get("n") and g1["pass"] >= math.ceil(g1["n"] * 0.6)):
            problems.append(f"대조 {row['name']}: G1 {g1.get('pass')}/{g1.get('n')} (PASS 예상)")
        if "teaser" in want and g1.get("teaser") is not want["teaser"]:
            problems.append(f"대조 {row['name']}: teaser={g1.get('teaser')} ({want['teaser']} 예상)")

    for art, want in CANARIES:
        try:
            got = set(judge(art)["matches"])
        except Exception as exc:
            problems.append(f"카나리아 '{art['title'][:30]}': {type(exc).__name__}")
            continue
        if not (want <= got and (want or not got)):
            problems.append(f"카나리아 '{art['title'][:30]}': {sorted(got)} ({sorted(want)} 예상)")

    jobs = [(row, a) for row in rows if row["group"] != "대조" for a in row["_recent"]]
    def safe(job):
        try:
            return job[0]["name"], judge(job[1])
        except Exception as exc:
            return job[0]["name"], {"title": job[1]["title"][:90], "error": f"{type(exc).__name__}: {exc}"[:120]}
    with ThreadPoolExecutor(6) as pool:
        judged = list(pool.map(safe, jobs))
    for row in rows:
        row.pop("_recent")
        if row["group"] == "대조":
            continue
        row["fit_items"] = [v for n, v in judged if n == row["name"]]
        row["fit"] = fit_summary(row["fit_items"])

    errors = sum(1 for _n, v in judged if "error" in v)
    stem = "probe_topics" + (f".{tag}" if only else "")
    out = f"{stem}.json" if not errors and not problems else f"{stem}.partial.json"
    with open(os.path.join(HERE, out), "w", encoding="utf-8") as fh:
        json.dump({"measured_at": NOW.isoformat(), "ua": UA["User-Agent"], "body_min": BODY_MIN,
                   "n_g1": N_G1, "n_fit": N_FIT, "fit_max_age_d": FIT_MAX_AGE_D,
                   "topics": TOPICS, "discard": DISCARD, "problems": problems,
                   "judge_errors": errors, "rows": rows, "elapsed_s": round(time.time() - t0, 1)},
                  fh, ensure_ascii=False, indent=1)
    # per topic: matches/judged, and that share times the feed's rate per day
    print(f"\n{'소스':<22}{'/일':>6}{'최신h':>7}{'G1':>5}{'티저':>6} {'G3':<10}"
          + "".join(f"{n:>13}" for n in TOPICS) + f"{'버림':>5}{'요약無':>5}  표시")
    for row in rows:
        if row["group"] == "대조":
            continue
        if row["feed"] != "OK":
            print(f"{row['name']:<22}{row['feed']} {row.get('why', '')}")
            continue
        g1, g2, fit = row["g1"], row["g2"], row["fit"]
        rate, judged = g2["per_day"] or 0, fit["judged"] or 1
        flags = [f for f, on in (("날짜없음", g2["nodate"] == g2["entries"]),
                                 ("미래날짜", (g2["newest_h"] or 0) < 0),
                                 ("7일넘게멈춤", (g2["newest_h"] or 0) > 168),
                                 ("본문못받음", g1["pass"] == 0)) if on]
        print(f"{row['name']:<22}{rate:>6}{str(g2['newest_h']):>7}{g1['pass']:>3}/{g1['n']}"
              f"{str(g1.get('teaser')):>6} {row['g3']['verdict']:<10}"
              + "".join(f"{fit[n]:>4}/{fit['judged']:<2}≈{fit[n] / judged * rate:>5.1f}" for n in TOPICS)
              + f"{fit['discard']:>5}{fit['no_summary']:>5}  {' '.join(flags)}")
    print(f"\n-> {out} ({time.time() - t0:.0f}s) · 판정 오류 {errors}건")
    for p in problems:
        print("!!", p)
    if errors or problems:
        raise SystemExit("대조·카나리아 불일치 또는 판정 오류: 표를 믿기 전에 원인부터 볼 것")
