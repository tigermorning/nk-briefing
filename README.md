# nk-briefing

북한 뉴스 수집→선별 파이프라인. 모두의연구소 캠프 136 뉴스레터 에이전트 과정 노트를 북한 뉴스 소스에 적용한 것.

진행 상황·소스 편성·남은 일은 [HANDOFF-nk-news-briefing.md](HANDOFF-nk-news-briefing.md) 참고.

## 실행

```
python collect_nk.py 72      # 72시간 창으로 수집
python test_g1.py            # G1 원문추출 게이트
python test_g23.py           # G2 14일 집계 + G3 robots.txt
python test_guards.py        # 조용한 실패 가드 3종 발화 재현
```

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
- **키는 저장소 밖에 둔다.** `DATA_GO_KR_KEY`는 별도 `.env`에서 읽고,
  값을 출력하지 않는다(길이만 확인).
