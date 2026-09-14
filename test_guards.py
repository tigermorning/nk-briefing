import collect_nk as C

REAL = list(C.SOURCES)
CASES = [
    ("baseline (nothing broken)", REAL),
    ("DNS gone (Yonhap)",
     [("Yonhap-NK", "https://no-such-host-xyz.invalid/rss.xml", True)] + REAL[1:]),
    ("200 but empty feed (Yonhap)",
     [("Yonhap-NK", "https://www.yna.co.kr/robots.txt", True)] + REAL[1:]),
    ("alive but contributes 0 (DailyNK, 0h window)", REAL),
]

for label, srcs in CASES:
    C.SOURCES = srcs
    hours = 0 if "0h window" in label else 72
    res = C.collect({"hours": hours})
    print(f"\n--- {label}")
    print(f"    total={len(res['items'])}")
    for d in res["dead"]:
        print(f"    !! DEAD   {d['source']}: {d['reason']}")
    for n in res["silent"]:
        print(f"    !! SILENT {n}: responded OK but contributed 0")
    if not res["dead"] and not res["silent"]:
        print("    all sources accounted for")

C.SOURCES = REAL
