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
