# -*- coding: utf-8 -*-
"""One briefing run. GitHub Actions calls this every morning.

Locally the keys come from the .env named in graph.ENV; in Actions they come
from repository secrets. Only DRY_RUN=0 sends, so a local run never posts.
Exit code 1 when the run published a failure notice, so Actions goes red.
"""
import os, sys
import graph

if __name__ == "__main__":
    graph.load_env()
    hook = bool(os.environ.get("DISCORD_WEBHOOK_URL"))      # presence only, never the value
    print("모드:", "dry-run" if graph.is_dry() else "발행", "· 웹훅 주소", "있음" if hook else "없음")
    out = graph.run()
    for line in out["log"]:
        print(line)
    if out["meta"].get("failed"):
        sys.exit(1)
