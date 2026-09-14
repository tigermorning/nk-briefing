# -*- coding: utf-8 -*-
"""Shared setup for the course step 6-8 experiments on North Korea articles.

Inputs are frozen by inputs.py into exp/*.json so every experiment reads the
same candidates. The criteria text is the pipeline's own (audience.yaml), not
the course's AI-news rubric, so results speak to this briefing.
"""
import json, pathlib, re, sys
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(errors="replace")

import graph                                   # noqa: E402  (after sys.path)

graph.load_env()
EXP = pathlib.Path(__file__).resolve().parent
MODEL = graph.MODEL
CRITERIA = graph.CRITERIA

def client():
    return graph.llm()

def chat(system, user, temperature=0.0, max_tokens=None, **kw):
    r = client().chat.completions.create(
        model=MODEL, temperature=temperature, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kw)
    return r

def load(name):
    return json.loads((EXP / name).read_text(encoding="utf-8"))

def save(name, obj):
    (EXP / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")

def pmap(fn, xs, workers=8):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, xs))

def first_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None

def short(s, n=34):
    s = re.sub(r"\s+", " ", s or "")
    return s if len(s) <= n else s[:n - 1] + "…"
