import re, requests
UA = {"User-Agent": "Mozilla/5.0 (newsletter-agent-course)"}
IDX = [
    ("voa", "https://www.voakorea.com/rssfeeds"),
    ("chinanews", "https://www.chinanews.com.cn/rss/"),
    ("jpyna", "https://jp.yna.co.kr/channel/rss"),
]
for n, u in IDX:
    try:
        html = requests.get(u, headers=UA, timeout=20).text
        links = sorted(set(re.findall(r'href=["\']([^"\'<>]*[Rr][Ss][Ss][^"\'<>]*)["\']', html)))
        print("==", n)
        for l in links[:15]:
            print(" ", l)
    except Exception as e:
        print("==", n, "ERR", e)
