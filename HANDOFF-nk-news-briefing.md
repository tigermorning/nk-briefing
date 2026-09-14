# HANDOFF — 북한 뉴스 브리핑 파이프라인

최종 갱신 2026-09-14. 다른 에이전트가 이어받기 위한 백로그. 로컬 실행 기준, API 키는 파일에만 존재(채팅에 없음).

## 목표
수업(모두의연구소 캠프 136, 뉴스레터 에이전트 과정) 노트 순서대로 북한 뉴스 수집→선별 파이프라인 구축.
최종: 양질의 최신 북한 뉴스 브리핑 (속보枠 + 심층枠 + 1차枠).

## 소스 편성
| tier | 소스 | 피드 | 상태 |
|---|---|---|---|
| tier1 (1차) | 통일부 북한동향 API | `http://apis.data.go.kr/1250000/trend/getTrend` | **동작 확인. 단 요약 전용 소스.** 평일만 발행, 지연 1영업일. 30일 73건. `url` 상세페이지는 `cn` + 장식 319자뿐이라 원문이 없다 |
| tier2 속보 | 연합뉴스 북한 | `https://www.yna.co.kr/rss/northkorea.xml` | 90건/7일, 요약 70~88자, G1·G2·G3 통과 |
| tier2 전문 | DailyNK | `https://www.dailynk.com/feed` | 10건창이지만 하루 3건 발행이라 3.3일치를 담는다. 최대 버스트 6건/24h, 여유 4건 — **1회/일 수집으로 충분** |
| tier3 주간 | 38North | `https://www.38north.org/feed/` | 8건/2주, 영문 장문, G1 3/3 (2,940~19,989자). 일간 기여 0 정상 |
| 후보 | RFA 한국어 | `https://www.rfa.org/korean/rss2.xml` | 30건, G1 3/3. 24h 기여 0 / 72h 기여 2 |
| 탈락 | NK News | `https://www.nknews.org/feed/` | 300건/14일 46건으로 G2는 통과. **유료벽 티저** — G1 5/5 PASS지만 길이 1008~1224로 고르고 문장이 중간에 끊김 (`test_g1_paywall.py`) |
| 탈락 | 중국신문망 국제 | `https://www.chinanews.com.cn/rss/world.xml` | 종합국제 30건 중 북한 키워드 1건. 일간 FAIL — `test_g2_filter.py` |

탈락: DailyNK 영문(`/english/rss-feed/`, 200이나 0건) · 연합뉴스 일문 북한(`https://jp.yna.co.kr/RSS/nk.xml`, G2는 16/16 통과하지만 동사 번역이라 신규신호 없음)
미확보: VOA 한국어 — voakorea.com/rssfeeds 목록이 JS 구동, 직접 피드 URL 못 찾음

중국신문망에서 걸린 1건이 조선중앙통신(朝中社) 인용 기사였다. 종합 피드를 필터해 쓰기엔 양이 안 나오지만, **KCNA 인용을 직접 받는 경로**는 따로 찾아볼 값어치가 있다 (통일부 API와 함께 1차枠 후보).

## 완료
1. RSS 상태표 3열 해석(건수/요약길이/최신글) — `test_rss.py`
2. 1차/2차 구분 + tier 면제·상한 설계
3. **G1** 원문추출 게이트 — 기존 4소스 12/12 PASS (4소스x3건, 기준 600자). 판정이 PASS/FAIL 2값이 아니라 `FETCH_ERR`/`FETCH_HTTP`/`EXTRACT_EMPTY`/`SHORT`/`PASS` 5값. `rss_len`은 긴데 `EXTRACT_EMPTY`면 "추출기 문제" 자동 경고
4. **G2** 14일 집계 + 임계값 일간枠 14d≥7 / 주간枠 14d≥1 — `test_g2.py` (8소스). 날짜를 `published_parsed` 하나만 보지 않고 `updated_parsed`/`created_parsed` 까지 폴백 — "날짜가 없는 것"과 "내가 안 본 필드에 있는 것"을 가름
   실측 14d: Yonhap 89 / DailyNK 10 / RFA 27 / NKNews 46 / Chinanews 30 / Yonhap-JP 16 / **38North 6 (일간 FAIL, 주간 PASS)** / DailyNK-EN 빈 피드 DEAD
5. **G3** robots.txt — 9/9 허용
6. **G1 보강** — 길이 기준만으로는 유료벽 티저를 못 거른다. NK News가 600자 기준을 5/5로 통과했지만 본문이 아니라 티저였다. 신호 두 개를 같이 본다 (`test_g1_paywall.py`)
   - `spread` = 최장/최단. 진짜 본문은 길이가 널뛴다 (38North 8.5x). 티저는 일정 (NK News 1.2x)
   - `cut` = 꼬리 문구(이메일·바이라인·저작권)를 떼고 난 뒤 문장이 종결부호로 끝나는가
   - **둘 다여야 티저.** 첫 판은 꼬리 문구를 안 떼서 연합·RFA를 5/5로 오판했다. 휴리스틱은 정상 소스에 먼저 돌려 봐야 한다
7. 수집노드 `collect(state)`: 시간창 + utm 꼬리표 제거 중복제거 + dead 격리. 조용한 실패 가드 4종:
   (a) `200 + 빈 피드`를 예외로 승격 (b) `dead`에 `reason` 동봉 (c) 소스별 `kept/old/dup/nodate` 합계 (건별 로그 아님) (d) `expect_daily` 소스가 응답 정상인데 기여 0이면 `SILENT` 경고 (e) 피드 최고참이 지난번 최신보다 새로우면 `GAP` 경고
8. 실측: 시간창 6h:7 / 24h:13 / 72h:41건. 소스 추가(RFA)해도 창 밖이면 기여 0
9. **통일부 API 연결** (`mou_api.py`) — 필수 파라미터 `pageNo` / `numOfRows` / `cl` / `bgng_ymd` / `end_ymd`. 응답 필드 `cl` 기간분류 · `sj` 제목 · `cn` 내용 · `url` · `dwld_url` · `filenm` · `first_reg_ymd`
   - 그동안의 403은 활성화 대기가 아니라 **이중인코딩**이었다. `.env` 에 든 건 인코딩키인데 `requests` 의 `params=` 가 한 번 더 인코딩했다. `load_key()` 가 `%` 를 보면 `unquote()` 한다
   - 발행 리듬: 평일만. 9/5·9/6·9/12·9/13(주말) 없음. 월요일 아침에 달력 기준으로 재면 `lag=3` 으로 보이지만 실제는 1영업일 — **감시는 영업일로 셀 것**
   - 신호 종류: 노동신문·조선중앙통신 인용 요약(사상사업 논조, 친선국 축전 등). 연합·DailyNK가 안 다루는 내부 선전 동향이라 RSS와 겹치지 않는다
10. **통일부 원문 G1** (`test_g1_mou.py`) — 30일 73건. `SHORT` 56 / `PASS` 17. 그런데 `PASS` 17건도 본문이 아니다
    - `ext_len - cn_len` 이 73건 전부에서 **300~338 (평균 319)**. 상세페이지는 `cn` 과 똑같은 글에 페이지 장식만 붙는다. 가져와도 새 글자가 0이다
    - 즉 `PASS` 는 `cn(317~784) + 장식 319` 가 600을 넘은 것. NK News 티저에 이은 세 번째 헛통과. **길이가 아니라 증가분(`ext_len - cn_len`)을 봐야 한다** — 스크립트가 `NO_GAIN` 으로 경고한다
    - `cn >= 300` 사전필터: 17/17 정확, fetch 56회 절약. 네트워크는 아끼지만 없는 본문을 만들지는 못한다
    - 30일 중 `cn >= 300` 인 날 15일 (영업일 약 22일 중)
    - **G3**: nkinfo는 robots.txt가 없다(모든 경로 400 + HTML 에러페이지) → 표준 해석상 허용. 400 본문을 파싱하면 "규칙 없음 = 전부 허용"으로 읽히니 상태코드를 먼저 볼 것
11. **1차枠 규칙 확정** (`tier1_mou.py`) — 원문이 없는 소스라 `cn >= 300` 인 날만 枠을 연다. 30일 시뮬레이션: **주말 제외 21일 중 15일(71%) OPEN**
    - 빈 날을 한 상태로 뭉치지 않는다. `BELOW_BAR`(발행은 됐고 전부 300자 미만 — 규칙이 일한 것) / `NO_PUBLICATION`(그날 발행 자체가 없음) / `DEAD`(API 실패). 셋을 "오늘 1차枠 없음"으로 합치면 API가 죽어도 몇 주씩 안 들킨다
    - 주중 `NO_PUBLICATION` 2건은 8/17(광복절 대체공휴일)과 당일분 미게시였다. **주중 공백은 공휴일부터 확인하고 그다음에 의심할 것**
12. **수집주기 측정** (`test_cadence.py`) — "10건창이라 1회/일이면 넘친다"는 가정이었고, 재보니 틀렸다
    - 피드가 보여주는 창은 건수가 아니라 **최신-최고참 간격**이다. DailyNK 10건 = 78.9시간치, 하루 3.0건
    - 평균은 버스트를 가리니 가장 바빴던 24h도 쟀다. DailyNK 6건(창 10건, 여유 4). Yonhap 19/89, RFA 5/30, 38North 2/8 — **전부 1회/일로 안전**
    - DailyNK 피드는 `?paged=2` 를 줘도 같은 10건이라 과거로 더 못 판다. 표본이 3.3일치뿐이므로 측정만 믿지 않고 탐지를 붙였다
    - `collect_nk.py` 에 **GAP 감시** 추가: `store/last_seen.json` 에 소스별 최신 시각을 남기고, 다음 실행에서 피드의 최고참이 그보다 **더 최신**이면 그 사이 기사가 통째로 빠진 것이다. 넘침은 흘린 걸 볼 방법이 없는 전형적인 조용한 실패라 탐지가 없으면 영원히 안 들킨다
13. **최소발행 규칙 확정** (`min_publish.py`) — `MIN_ITEMS=5`, 사다리 24h → 48h → 72h
    - 먼저 얼마나 마르는지 쟀다 (`test_minpub.py`). 정직하게 시뮬레이션 가능한 범위는 **가장 짧은 피드가 정한다** — DailyNK 때문에 최근 80.3h뿐이고, 그보다 오래된 창은 그 소스가 인위적으로 0이 되어 없는 흉년을 만들어낸다
    - 5개 창 결과 min 7 / mean 11.6 / max 15. **3건 미만은 0회.** 그래서 이 규칙은 상시 장치가 아니라 바닥 안전망이고, 관측 최소(7)보다 낮은 5로 잡았다. 실제로 마르는 건 소스 사망·공휴일이며 그건 `DEAD`/`GAP`/`NO_PUBLICATION` 이 잡는다
    - **창 확장의 함정**: 48h로 넓히면 어제 브리핑이 이미 낸 기사를 다시 긁는다. `store/published.json` 원장으로 이미 발행한 링크를 빼야 확장이 재탕 생산기가 되지 않는다
    - `mark_published()` 는 **발행 단계에서만** 호출한다. 수집만 되고 안 실린 항목은 내일도 후보로 남아야 한다
    - 확장하면 `ESCALATED` 를 띄운다. "오늘"이라고 받은 독자에게 사흘치 그물이었다는 건 알려야 한다
    - 72h에도 미달이면 `BELOW_MIN` 으로 **적게 낸다.** 숫자를 채우려 오래된 걸 끼우는 건 이 파이프라인이 막으려는 실패 그 자체다
    - 세 경로 모두 발화 확인 (정상 24h / 확장 48h / 미달 72h)
14. `store/metrics.jsonl` 매 실행 append — 게이트 결과·소스별 기여·skips·elapsed

## 남은 일
1. **`cl` 주간·월간 코드 확인** — 포털이 문서화한 건 `ARGUMENT_DAIL` 하나뿐. `ARGUMENT_WEEK`/`ARGUMENT_MONT` 는 추측이고 둘 다 0건인데, **`NO_SUCH_CODE_XYZ` 도 똑같이 `resultCode 0 / totalCount 0 / normal_code`** 다. 0건이 "발행 없음"인지 "코드 틀림"인지 이 API로는 못 가른다. 포털 상세문서나 nkinfo 사이트에서 실제 코드를 확인할 것. 확인 전까지 주간·월간은 "없다"고 적지 말 것
2. **브리핑 품질바 확정** — 속보枠=원문필수(요약만이면 탈락), 심층枠=38North형 주간, 1차枠=통일부 고정1枠(경쟁면제·검사유지·상한)
3. VOA 한국어 피드 URL 수동 확인
4. **KCNA 인용을 직접 받는 경로 조사** — 1차枠 후보. 중국신문망 필터에서 조선중앙통신 인용 1건이 나온 게 단서

## 파일 (저장소 루트 `C:\Users\user\Documents\nk-briefing` 기준)
| 파일 | 용도 |
|---|---|
| `mou_api.py` | 통일부 API 클라이언트. `get_trend(period, days)` |
| `mou_probe.py` | 갱신속도·신호종류 측정. 보고서는 `mou_report.txt` (UTF-8) |
| `tier1_mou.py` | 1차枠 규칙 + 30일 시뮬레이션 |
| `test_g1_mou.py` | 통일부 상세페이지 G1/G3 + `NO_GAIN` 판정 |
| `min_publish.py` | 최소발행 규칙 + 발행 원장 `store/published.json` |
| `test_minpub.py` | 24/48/72h 창 시뮬레이션 |
| `test_cadence.py` | 피드 창 길이·발행속도·버스트 측정 |
| `test_rss.py` | RSS 상태표 |
| `test_g1.py` | G1 원문추출 게이트 (5값 판정) |
| `test_g1_paywall.py` | 유료벽 티저 판별 (spread + cut) |
| `test_g1_nknews.py` | NK News 단독 G1 |
| `test_g2.py` | G2 14일 집계 (날짜 필드 폴백 포함) |
| `test_g2_filter.py` | 종합 피드에 키워드 필터를 건 뒤 G2 재측정 |
| `test_g23.py` | 옛 G2+G3 합본. G3 부분만 유효 |
| `collect_nk.py` | 수집노드. `python collect_nk.py [hours]` |
| `test_guards.py` | 조용한 실패 가드 3종 발화 재현 |
| `test_silent.py` | 기록 유/무 대비 데모 |
| `test_g1_sweep.py` | G1 임계값 200/600/1500/4000 비교 |
| `test_g1_ua.py` | `fetch_url` vs `requests+UA` 비교 |
| `check_idx.py`, `check_cand.py` | 후보 피드 검증 |
| `store/metrics.jsonl` | 실행 메트릭 append. 1~2행은 38North 오판 포함 — 감사추적용 보존, 분석은 최신행 |
| `openai_key.env` | 별개 파일, 건드리지 말 것 |

키 위치: `C:\Users\user\Documents\tigermorning.github.io\ko\.env` 의 `DATA_GO_KR_KEY` — **인코딩키**(길이 92, `%XX` 포함). `mou_api.load_key()` 가 `unquote()` 해서 넘긴다. **절대 채팅/셀에 출력 금지, 길이만 확인.** `requests` 가 키를 쿼리스트링에 넣으므로 `r.url` 도 출력 금지.

## 주의 (gotcha)
- PowerShell에 파이썬 코드 붙여넣기 금지. 파일 만들고 `python xxx.py` 로 저장소 폴더에서 실행. 메트릭 경로는 스크립트 위치 기준이라 어느 cwd에서 돌려도 `store/` 한 곳에 쌓인다
- `>` 로 `.env` 덮어쓰기 금지. `>>` 또는 에디터로 1행 추가
- 한글 콘솔 출력 깨짐(cp949)은 무시. 내용은 정상. 다만 중국어는 깨지는 정도가 아니라 `UnicodeEncodeError` 로 죽으니 `sys.stdout.reconfigure(errors="replace")` 를 걸 것
- data.go.kr 키: `requests` `params=` 로 넘길 땐 **디코딩키**. `.env` 에 든 건 인코딩키라 그대로 넘기면 이중인코딩되고, 돌아오는 건 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`(code 30)다. 죽은 키처럼 읽히지만 망가진 키다
- data.go.kr `totalCount` 는 건수가 있을 땐 int, 0일 땐 문자열 `'0'` 으로 온다. 타입 비교 금지
- **틀린 `cl` 코드와 빈 결과가 같은 응답**이다. 우리 쪽에서 화이트리스트로 막지 않으면 오타가 "그날 발행 없음"으로 둔갑한다
- **robots.txt를 받을 땐 상태코드부터 본다.** nkinfo는 400에 HTML 에러페이지를 준다. 그걸 `parse()` 에 넣으면 "규칙 없음 = 전부 허용"이 되어, 진짜 허용인지 못 받은 건지 구별이 사라진다
- **시뮬레이션 범위는 가장 짧은 피드가 정한다.** 그보다 깊이 들어가면 그 소스가 0이 되어 없는 흉년이 생긴다
- **피드의 창 크기는 건수가 아니라 시간이다.** 10건 창이 좁은지는 그 소스의 발행속도가 정한다. 재보기 전에 "넘친다"고 적지 말 것
- **원문 추출은 길이가 아니라 증가분으로 판단한다.** `ext_len` 이 커도 `ext_len - cn_len` 이 상수면 페이지 장식만 붙은 것이다
- `str.replace` 는 패턴이 안 맞아도 원본을 그대로 돌려준다. 패치 스크립트는 반드시 `assert old in s` 를 걸 것 — 안 걸면 "수정했다"는 출력만 남고 파일은 그대로다
- **`RobotFileParser`** 는 UA 없는 urllib 사용 → 403 사이트에서 "전체차단" 오판. `requests`+UA로 본문 받아 `parse()` 할 것
- **`trafilatura.fetch_url()`** 도 같은 함정. 기본 UA가 차단당하면 `None` 반환 → 추출 0자 → "본문 없는 소스"로 오판. `requests`+UA로 받아 `extract(r.text)` 할 것
- **게이트 통과가 쓸 수 있다는 뜻은 아니다.** 길이 기준은 유료벽 티저를, G2는 번역 중복을 못 본다. 기준을 올려 막을 수도 없다 — 1500자로 올리면 연합(943자)이 같이 떨어진다
- 위 둘의 공통형: **라이브러리가 조용히 빈 값/False를 돌려줌.** 빈 결과를 사실로 읽지 말고 HTTP code를 같이 찍을 것
