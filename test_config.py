# -*- coding: utf-8 -*-
"""audience.yaml typos must stop the run at start-up. No key, no network."""
import pathlib, sys, tempfile
import graph

sys.stdout.reconfigure(errors="replace")
GOOD = (graph.HERE / "audience.yaml").read_text(encoding="utf-8")

CASES = [
    ("정상 파일", GOOD, None),
    ("키 오타 버릴_것 → 버릴것", GOOD.replace("버릴_것:", "버릴것:"), "버릴것"),
    ("색 형식", GOOD.replace('"#8F2D2D"', '"red"'), "색"),
    ("빈 기준 문장", GOOD.replace('"미사일 발사·핵시설 가동·병력 이동 같은 북한의 군사 행동이 실제로 있었나"', '""'), "중요도_기준"),
    ("토픽 이름 중복", GOOD.replace('이름: "대남"', '이름: "군사·핵"'), "겹침"),
    # P1: sources, role and tier1 moved into the yaml, so their typos must stop the run too
    ("소스 이름 중복", GOOD.replace('이름: "DailyNK"\n', '이름: "Yonhap-NK"\n'), "소스: 이름이 겹침"),
    ("칸 오타", GOOD.replace("칸: 심층\n    매일기대: false\n    언어: \"영어\"", "칸: 주간\n    매일기대: false\n    언어: \"영어\""), "칸"),
    ("소스 키 오타 키워드 → 키워드들", GOOD.replace("    키워드: [", "    키워드들: [", 1), "키워드들"),
    ("주소 형식", GOOD.replace('주소: "https://www.dailynk.com/feed"', '주소: "www.dailynk.com/feed"'), "주소"),
    ("매일기대 값", GOOD.replace("매일기대: true", "매일기대: 매일", 1), "매일기대"),
    ("1차칸 오타", GOOD.replace('1차칸: "통일부"', '1차칸: "통일부 북한동향"'), "1차칸"),
    ("1차칸 줄 빠짐", GOOD.replace('1차칸: "통일부"\n', ""), "1차칸"),
    ("제목에 discord", GOOD.replace('제목: "북한 브리핑"', '제목: "Discord 북한 브리핑"'), "제목"),
    ("소스 이름에 쉼표", GOOD.replace('이름: "RFA-KO"', '이름: "RFA,KO"'), "이름"),
    ("소스 주소 중복", GOOD.replace('주소: "https://www.dailynk.com/feed"', '주소: "https://www.yna.co.kr/rss/northkorea.xml"'), "소스 주소: 같은 주소가 겹침"),
    ("따옴표 친 불리언", GOOD.replace("매일기대: true", 'Q', 1).replace('Q', '매일기대: "true"'), "매일기대"),
    ("기자역할 빠짐", GOOD.replace('기자역할: "북한 뉴스 브리핑 기자"\n', ""), "기자역할"),
    ("속보 소스 없음", GOOD.replace("칸: 속보", "칸: 심층"), "속보인 소스가 하나도 없음"),
]

ok = True
for label, text, expect in CASES:
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "audience.yaml"
        p.write_text(text, encoding="utf-8")
        assert text != GOOD or expect is None, f"{label}: replacement did not apply"
        try:
            graph.load_cfg(p)
            got = None
        except SystemExit as exc:
            got = str(exc)
    passed = (got is None) if expect is None else (got is not None and expect in got)
    ok &= passed
    print(f"{'OK ' if passed else 'BAD'} {label}: " + ("통과" if got is None else got.splitlines()[1].strip()))

print("ALL OK" if ok else "FAILED")
sys.exit(0 if ok else 1)
