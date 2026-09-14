"""통일부 북한 동향 조회 서비스 — data.go.kr 1250000/trend/getTrend

Required params (per the portal spec): pageNo, numOfRows, cl, bgng_ymd, end_ymd.
Response fields: cl 기간분류, sj 제목, cn 내용, url, dwld_url, filenm.

The key lives in a .env outside this repo and is never printed. requests puts
it in the query string, so r.url must not be printed either.
"""
import io, sys, json, urllib.parse, requests
from datetime import datetime, timedelta

sys.stdout.reconfigure(errors="replace")

ENV = r"C:\Users\user\Documents\tigermorning.github.io\ko\.env"
URL = "http://apis.data.go.kr/1250000/trend/getTrend"
PERIODS = {"daily": "ARGUMENT_DAIL", "weekly": "ARGUMENT_WEEK", "monthly": "ARGUMENT_MONT"}

def load_key(name="DATA_GO_KR_KEY"):
    for line in io.open(ENV, encoding="utf-8"):
        if line.startswith(name + "="):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            # data.go.kr issues an ENCODED and a DECODED key. This .env holds the
            # encoded one, and requests percent-encodes params again. The double
            # encoding comes back as SERVICE_KEY_IS_NOT_REGISTERED_ERROR, which
            # reads like a dead key rather than like a mangled one.
            return urllib.parse.unquote(v) if "%" in v else v
    raise SystemExit(f"{name} not found in {ENV}")

def get_trend(period="daily", days=7, page=1, rows=10):
    end = datetime.now()
    params = {"serviceKey": load_key(), "pageNo": page, "numOfRows": rows,
              "cl": PERIODS[period],
              "bgng_ymd": (end - timedelta(days=days)).strftime("%Y%m%d"),
              "end_ymd": end.strftime("%Y%m%d")}
    r = requests.get(URL, params=params, timeout=30)
    if r.status_code != 200:
        return {"error": f"http {r.status_code}", "body": r.text[:300]}
    try:
        data = r.json()
    except ValueError:
        return {"error": "not json", "body": r.text[:300]}
    # check the code itself rather than scanning for known error strings -- a
    # marker list silently reports "no error" for any code it has not met
    code = str(data.get("resultCode", data.get("response", {})
                        .get("header", {}).get("resultCode", "")))
    if code not in ("00", "0", ""):
        return {"error": f"resultCode {code}",
                "msg": data.get("resultMsg", ""), "raw": data}
    return data

if __name__ == "__main__":
    period = sys.argv[1] if len(sys.argv) > 1 else "daily"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    res = get_trend(period, days)
    print(json.dumps(res, ensure_ascii=False, indent=2)[:2500])
