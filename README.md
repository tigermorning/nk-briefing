# nk-briefing

북한 뉴스 브리핑 에이전트. 모두의연구소 캠프 136 뉴스레터 에이전트 과정(수집→선별→취재→검수→발행)을 북한 뉴스 소스에 적용한 것.

진행 상황·소스 편성·남은 일은 [HANDOFF-nk-news-briefing.md](HANDOFF-nk-news-briefing.md) 참고.

## 구조

| 파일 | 하는 일 |
|---|---|
| `graph.py` | LangGraph 한 판. 수집 → 선별 → 취재(기사마다 워커) → 검수 → 발행, 끝나면 `store/metrics.jsonl`에 한 줄 |
| `audience.yaml` | 독자·중요도 기준·버릴 것·토픽별 데스크지침. 편집 방향은 여기만 고친다 |
| `run.py` | 한 번 실행. GitHub Actions가 05:43(KST)에 깨워 07:30까지 기다린 뒤 돌린다. 08:13 예비 실행은 그날 이미 보냈으면 건너뛴다 |
| `scorecard.py` | 쌓인 기록으로 소스별 기여·깔때기·경보 누적을 본다 |
| `collect_nk.py` · `min_publish.py` · `tier1_mou.py` | 수집 노드가 쓰는 부품 (피드 수집·원장·통일부 1차枠) |

```mermaid
graph TD;
	__start__([start]) --> collect;
	collect --> select;
	select -.-> report;
	select -.-> verify;
	report --> verify;
	verify --> publish;
	publish --> __end__([end]);
```

`python -c "import graph; print(graph.build().compile().get_graph().draw_mermaid())"`로 다시 뽑는다.
점선은 조건부 엣지다. 고른 기사가 있으면 기사마다 `report` 워커가 펼쳐지고, 0건이면 `verify`로 바로 가서 발행까지 간다.

브리핑은 세 칸이다. **속보**(연합·DailyNK·RFA 한국어·데일리NK재팬, 24h 창, 모자라면 48h·72h, 소스당 3건),
**심층**(38North·아시아프레스, 7일 창, 최대 1건), **1차**(통일부 북한동향, 요약 300자 이상인 날만, 최대 1건).
하루 카드는 **3장**이다. 심층이나 1차가 있으면 3장 중 1장을 그것이 차지하고, 둘 다 있는 날만 4장이다.
속보는 예비까지 4건을 취재해 두고 검수 뒤에 칸 수만큼 선별 순위대로 싣는다. 안 실린 예비는 원장에 안 올라 내일 후보로 남는다.

## 실행

```
python test_graph_fake.py    # 키·네트워크 없이 그래프 모양 확인
python run.py                # 실제 수집·모델 호출. DRY_RUN 기본 1이라 디스코드로 안 보낸다
python scorecard.py          # 성적표 (--plot out.png 로 단계별 통과율 그래프)
python test_config.py        # audience.yaml 오타가 시작 시점에 잡히는지
python test_schedule.py      # 07:30 대기 계산과 하루 한 번 발송 판정
python test_number_check.py  # 강의식 문자열 숫자 대조가 북한 원문에서 틀리는 사례 (1/5)
python test_grounding.py     # 값 기준 숫자 대조·한정어·추정 표현 검사 (키 없음)
python exp/step12_exaggeration.py  # 실제 카드에 과장을 심어 옛 검수와 새 검수 비교 (키 필요)
python probe_sources.py      # 외국 후보 21곳 + 핵심 3곳 측정 (키 필요: 새 사건 판정)
python collect_nk.py 72      # 수집만, 72시간 창
python test_g1.py            # G1 원문추출 게이트
python test_g23.py           # G2 14일 집계 + G3 robots.txt
python test_guards.py        # 조용한 실패 가드 3종 발화 재현
```

로컬 키는 `graph.ENV`가 가리키는 `.env`(`OPENAI_API_KEY`, `DATA_GO_KR_KEY`)에서 읽는다.
Actions에서는 저장소 Secrets `OPENAI_API_KEY` · `DATA_GO_KR_KEY` · `DISCORD_WEBHOOK_URL`을 쓴다.
실제 발행은 `DRY_RUN=0`일 때만 하고, 발행 원장 `store/published.json`은 실제로 보낸 뒤에만 쓴다.

어느 폴더에서 실행해도 메트릭은 이 저장소의 `store/metrics.jsonl` 한 곳에 쌓인다.

## 이 저장소가 지키는 규칙

- **빈 결과를 사실로 읽지 않는다.** 라이브러리가 돌려준 `0`/`False`/`None`은
  "없음"일 수도 "못 받음"일 수도 있다. HTTP 상태코드를 같이 남겨 둘을 가른다.
  (`urllib.robotparser`와 `trafilatura.fetch_url()`이 각각 한 번씩 이걸로 오판을 만들었다)
- **결과를 바꾸는 건너뜀만 기록한다.** 소스 하나가 통째로 빠지는 건 `dead`에
  이유와 함께 남기고, 항목 한 건이 시간창 밖이라 빠지는 건 소스별 합계로만 센다.
  전부 적으면 진짜 신호가 노이즈에 묻힌다.
- **`store/metrics.jsonl`은 고치지 않는다.** 앞쪽 두 행에는 나중에 오판으로
  밝혀진 값이 들어 있다. 그대로 두는 게 "언제 무엇을 잘못 알았는지"의 기록이다.
- **숫자는 값으로 원문과 맞춘다.** 헤드라인·요약·💡 문장의 숫자가 원문에 없거나, 원문의 `최대`·`추정`이
  빠지면 검수에서 떨어진다(`grounding.py`). 모델 검수는 `100억 → 1,000억 달러`를 6번 모두 통과시켰다.
  떨어진 카드는 지적 사항을 보여 주고 한 번 다시 쓰게 하고, 그래도 틀리면 빼고 예비 기사로 채운다.
- **프롬프트 부탁은 코드로 확인한다.** 같은 사건 거르기는 모델이 붙인 라벨만 믿지 않고,
  뽑힌 짧은 목록을 한 번 더 나란히 놓고 묶게 한 뒤 예비 후보로 채운다.
- **키는 저장소 밖에 둔다.** `DATA_GO_KR_KEY`는 별도 `.env`에서 읽고,
  값을 출력하지 않는다(길이만 확인).
