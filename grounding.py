# -*- coding: utf-8 -*-
"""Every number in a draft has to exist in the source, by value.

Why a code check next to the LLM judge: measured 2026-09-15 on the real
Yonhap card sent that morning (exp/step12_exaggeration.log), the judge passed
"100억 달러" rewritten as "1,000억 달러" and "1천억 달러" 6 times out of 6,
while it caught 5x money, 10x casualties and an invented sentence every time.
A tenfold figure is a distortion no matter how the rest of the card reads,
and comparing values does not depend on the model's mood.

Why values and not strings: the course's digit-substring check got 1 of 5
right on North Korea text (test_number_check.py). "35,000" is "3만5000" in the
source, "５～６" is full width, and "20" hides inside "2023". Here both sides
are parsed to numbers first: 3만5000 == 35,000 == 3万5000 == 35 thousand.

Three findings, each only for quantities (not dates, times, phone numbers):
  ungrounded      the value is not in the source
  dropped_bounds  "최대 5만명" written "5만명": a ceiling became a fact
  dropped_hedges  "약 2천300명으로 추정" written "2천300명": an estimate became a count
The LLM judge passed both of the last two 3 of 3, old prompt and new.

Written after a review that ran each of these against the first version:
  - rounding may only use source numbers that are quantities: within 10% for a
    plain figure, 20% after 약, source up to 1.3x for 여/이상.
    "2024년" and "02-398-3000" in a byline had grounded "2천명" and "3천명"
  - bound and hedge words have to touch the number. "최고사령관이 1만3천명",
    "1만3천명 이상기후" and a "가능성" in the next sentence had all counted
  - each field is checked on its own: a hedge in the headline does not cover
    a bare number in the summary

What it cannot see, left to the LLM judge:
  - a real number attached to the wrong thing (rice 6.5x / corn 5.5x swapped)
  - hedges that are not next to a number ("전망된다" -> "확실하다")
  - small counts (10 or less), which sources often spell as words
  - dates, and a unit swapped for another (100억원 -> 100억 달러)
"""
import re
import unicodedata
from decimal import Decimal

NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
BIG = {"조": 12, "兆": 12, "억": 8, "億": 8, "만": 4, "万": 4}
SMALL = {"천": 3, "千": 3, "백": 2, "百": 2}
UNITS = "".join(BIG) + "".join(SMALL)
MULT = {"hundred": 2, "thousand": 3, "million": 6, "mn": 6, "billion": 9, "bn": 9, "trillion": 12}
EN_NUM = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
EN_NUM.update({"a": 1, "an": 1})
# "30여만명", "1천여만": 여 may sit before or after a unit. A unit may be
# followed by a space only when the next piece carries its own unit ("1만 3천").
STACK = rf"[{UNITS}](?:여?[{UNITS}])*여?"      # 1천억, 3천만, 1천여만
KOREAN = rf"(?:{NUM})여?{STACK}(?:\s?(?:{NUM})여?{STACK}|(?:{NUM})(?:{STACK})?)*"
ENGLISH = rf"(?:{NUM}|\b(?:{'|'.join(EN_NUM)}))\s?(?:{'|'.join(MULT)})(?:\s(?:{'|'.join(MULT)}))?\b"
TOKEN = re.compile(rf"{KOREAN}|{ENGLISH}|{NUM}", re.I)
SMALL_MAX = 10
ROUND_TOLERANCE = Decimal("0.10")      # plain figure: "2천300" may be "2천300", not "2천"
ABOUT_TOLERANCE = Decimal("0.20")      # "약 2천명" for 2,300
AT_LEAST_BAND = Decimal("1.30")        # "1만여명" / "1만명 이상" for 10,000..13,000

# a number followed by these is a date, time or duration, not a quantity. The
# suffix has to end the word or take a particle: "14일에", "3년간" are dates,
# "5만 시민", "30만 일자리", "50만 초과" are not (review 2026-09-15)
DATE_AFTER = re.compile(r"\s?(?:시간|개월|주년|ヶ月|か月|년|월|일|시|분|초|年|月|日|時|分|秒)"
                        r"(?=$|[^가-힣]|부터|가량|[에은는의이을를까도간째말중전후경만께여])")
LATIN_UNIT = re.compile(r"\s?(?:km|kg|kt|mw|mm|cm|m|t|ton|tons|톤)(?![a-z])", re.I)
EN_MONTH = re.compile(r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|"
                      r"sep|sept|september|oct|october|nov|november|dec|december)\.?\s?$", re.I)


def normalize(text):
    return unicodedata.normalize("NFKC", text or "")


def value(token):
    """'13조4천500억' -> 13450000000000, '1,000억' -> 100000000000,
    '10 billion' / 'ten billion' -> 10000000000, '30여만' -> 300000"""
    t = token.replace(",", "").replace("여", "")
    mults = list(re.finditer(rf"({'|'.join(MULT)})\b", t, re.I))
    if mults:                                   # "two million", "a hundred thousand"
        head = t[:mults[0].start()].strip().lower()
        base = Decimal(EN_NUM[head]) if head in EN_NUM else Decimal(head)
        return base * Decimal(10) ** sum(MULT[x.group(1).lower()] for x in mults)
    total = section = Decimal(0)
    current = None
    for num, unit in re.findall(rf"(\d+(?:\.\d+)?)|([{UNITS}])", t):
        if num:
            current = Decimal(num)
        elif unit in SMALL:
            section += (current if current is not None else 1) * Decimal(10) ** SMALL[unit]
            current = None
        else:
            section += current if current is not None else 0
            total += (section or 1) * Decimal(10) ** BIG[unit]
            section, current = Decimal(0), None
    return total + section + (current or 0)


class Num:
    __slots__ = ("token", "value", "start", "end", "kind")

    def __init__(self, norm, m):
        self.token, self.start, self.end = m.group(), m.start(), m.end()
        self.value = value(self.token)
        self.kind = kind_of(norm, m)


def kind_of(norm, m):
    """'date' for dates, times, phone numbers and ids; 'unit' for a quantity
    written with a unit, separator or counter; 'bare' for a plain number that
    may be a year or an id -- exact matches only."""
    t, before, after = m.group(), norm[max(0, m.start() - 1):m.start()], norm[m.end():m.end() + 2]
    if DATE_AFTER.match(norm, m.end()):
        return "date"
    if re.fullmatch(r"\d{1,2}", t) and EN_MONTH.search(norm[max(0, m.start() - 12):m.start()]):
        return "date"                           # "Sept. 14", not "marched 13,000" or "May 13,000"
    if (before in "-:/." and before and norm[max(0, m.start() - 2):m.start() - 1].isdigit()) or \
            (after[:1] in "-:/." and after[:1] and after[1:2].isdigit()):
        return "date"                           # 02-398-3000, 20:42, 2026.09.15
    if re.fullmatch(r"\d{1,2}", t) and (re.match(r"·\d{1,2}(?!\d)", norm[m.end():])
                                        or re.search(r"(?<!\d)\d{1,2}·$", norm[max(0, m.start() - 3):m.start()])):
        return "date"                           # 6·25, 9·19군사합의, 12·12
    latin_before = before.isascii() and before.isalpha()
    latin_after = after[:1].isascii() and after[:1].isalpha()
    if before and before in "/=_#&?" or (latin_before and latin_after):
        return "date"                           # ids in URLs and codes: news/12345, id=77, A4B
    if re.search(rf"[{UNITS}]|,|[a-z]", t, re.I) or len(t.replace(".", "")) >= 5 \
            or LATIN_UNIT.match(norm, m.end()):
        return "unit"                           # 8천t급, 1만5천km: a unit, not an id (review 2026-09-15)
    if re.match(r"(?:[가-힣ぁ-んァ-ン一-龥%$]|\s[a-z])", norm[m.end():m.end() + 2]):
        return "unit"                           # 2300명, 2000人, 50%, "300 troops"
    return "bare"


def scan(text):
    norm = normalize(text)
    return norm, [Num(norm, m) for m in TOKEN.finditer(norm)]


def numbers(text):
    """(token as written, value) for every number in the text"""
    return [(n.token, n.value) for n in scan(text)[1]]


def sig_digits(d):
    return len(d.normalize().as_tuple().digits)


def round_sig(b, sig):
    if b == 0:
        return b
    return b.quantize(Decimal(1).scaleb(b.adjusted() - sig + 1))


def matches(d, src_nums, draft_kind="unit", qualifier=""):
    """Source numbers that d stands for: exact values first; if none, near
    ones, only from quantities. How near depends on how the draft wrote it:
      plain        rounded to the draft's own digits and within 10%
      'about'      약·가량·안팎: within 20%
      'at_least'   여·이상·넘게·최소: source between d and 1.3 d
    A bare year-like number in the draft may also match a source date exactly
    (2026 아시안게임 / 2026년)."""
    exact = [n for n in src_nums if n.value == d and (n.kind != "date" or draft_kind == "bare")]
    if exact:
        return exact
    near = [n for n in src_nums if n.kind == "unit" and n.value > 0]
    if qualifier == "at_least":
        return [n for n in near if d <= n.value <= d * AT_LEAST_BAND]
    if qualifier == "about":
        return [n for n in near if abs(d - n.value) / n.value <= ABOUT_TOLERANCE]
    sig = sig_digits(d)
    return [n for n in near if round_sig(n.value, sig) == d and abs(d - n.value) / n.value <= ROUND_TOLERANCE]


def qualifier_of(norm, n):
    """How the draft itself qualifies the figure: '', 'about' or 'at_least'."""
    if "여" in n.token or SUFFIX_EST_AT_LEAST.match(norm, n.end):
        return "at_least"
    word = _bound_word(norm, n)
    if word in ("이상", "넘게", "넘는", "넘어", "최소", "적어도", "적게는"):
        return "at_least"
    if PREFIX_EST.search(norm[max(0, n.start - 15):n.start]) or SUFFIX_EST.match(norm, n.end):
        return "about"
    return ""


def _checked(draft_nums):
    return [n for n in draft_nums if n.kind != "date" and n.value > SMALL_MAX]


def ungrounded(text, body):
    """Numbers in text whose value is not in body. Small counts and dates are skipped."""
    _src, src_nums = scan(body)
    _draft, draft_nums = scan(text)
    bad = []
    for n in _checked(draft_nums):
        if not matches(n.value, src_nums, n.kind, qualifier_of(_draft, n)) and n.token not in bad:
            bad.append(n.token)
    return bad


# ---------------------------------------------------------------- bounds
# The word has to touch the number: "최대 5만명", "5만명 이상", "up to 50,000".
# "사상 최대 1만3천명" is a record, not a ceiling; "이상기후" is not "이상".
BOUND_BEFORE = re.compile(r"(?<!사상 )(?<!역대 )(?:최대|최소|많게는|적게는|적어도|最大|最多|最低|少なくとも|"
                          r"up to|at least|as many as|more than|fewer than|less than)\s?$", re.I)
BOUND_AFTER = re.compile(r"[^\s\d,.]{0,3}?\s?(?P<word>이상|이하|미만|초과|넘게|넘는|넘어|以上|以下|未満|を?超え)"
                         r"(?=$|[^가-힣]|[의이을은에으도가로])")


def _bound_word(norm, n):
    left = BOUND_BEFORE.search(norm[max(0, n.start - 14):n.start])
    if left:
        return left.group().strip()
    right = BOUND_AFTER.match(norm, n.end)
    if right:
        return right.group("word")
    return ""


def dropped_bounds(text, body):
    """Numbers bounded at every place they appear in the source, written bare
    in the text. Returns "원문 '최대' 5만"-style strings."""
    src, src_nums = scan(body)
    draft, draft_nums = scan(text)
    out = []
    for n in _checked(draft_nums):
        mine = _bound_word(draft, n)
        hits = matches(n.value, src_nums, n.kind, qualifier_of(draft, n))
        words = [_bound_word(src, h) for h in hits]
        if not (hits and all(words)):
            continue
        if not mine:
            item = f"원문 '{words[0]}' {n.token}"
        elif all(direction(w) and direction(w) != direction(mine) for w in words):
            # "최대 5만명" written "5만명 이상": a ceiling turned into a floor (review 2026-09-15)
            item = f"원문 '{words[0]}' {n.token}, 초안 '{mine}'"
        else:
            continue
        if item not in out:
            out.append(item)
    return out


UPPER = {"최대", "많게는", "最大", "最多", "up to", "as many as", "fewer than", "less than", "이하", "미만", "以下", "未満"}
LOWER = {"최소", "적게는", "적어도", "最低", "少なくとも", "at least", "more than", "이상", "초과", "넘게", "넘는", "넘어",
         "以上", "超え", "を超え"}


def direction(word):
    w = word.lower()
    return "upper" if w in UPPER else "lower" if w in LOWER else ""


# ---------------------------------------------------------------- hedges
# Source side counts only clear estimates, so an ordinary sentence does not
# make a figure "hedged": a prefix touching the number, a suffix touching it,
# or an estimate verb in the same clause. Draft side accepts more wording
# ("가능성", "전망", "알려졌다") anywhere in the same sentence.
PREFIX_EST = re.compile(r"(?<![가-힣])(?:약|約|대략|approximately|roughly|an estimated|estimated)\s?$", re.I)
# "2천300여명" is an estimate; "1만3천명이 여전히", "1만3천명의 여성" are not (review
# 2026-09-15): 여 counts only right after the number, before a counter
SUFFIX_EST_AT_LEAST = re.compile(r"\s?여(?=\s?[명개척대톤곳건원달배만억천])|[명개척대톤곳건원人]?\s?余り")
SUFFIX_EST = re.compile(r"(?:[명개척대톤곳건원人]|달러|ドル)?\s?(?:가량|안팎|남짓|쯤|前後|程度|ほど)")
SRC_VERBS = ("추정", "추산", "推定", "推計", "とみられ", "と見られ", "estimated")
DRAFT_WORDS = SRC_VERBS + ("가능성", "보인다", "보이", "보여", "전망", "예상", "관측", "알려", "주장", "추측", "대략")
CLAUSE_END = re.compile(r"[.,;!?。、\n]")
SENTENCE_END = re.compile(r"[.!?。\n]")


def _span(norm, n, stop, reach):
    left = norm[max(0, n.start - reach):n.start]
    cut = [m.end() for m in stop.finditer(left)]
    left = left[cut[-1]:] if cut else left
    right = norm[n.end:n.end + reach]
    m = stop.search(right)
    return left + n.token + (right[:m.start()] if m else right)


def _touching_estimate(norm, n):
    return "여" in n.token or bool(PREFIX_EST.search(norm[max(0, n.start - 15):n.start])) \
        or bool(SUFFIX_EST.match(norm, n.end)) or bool(SUFFIX_EST_AT_LEAST.match(norm, n.end))


def src_hedged(norm, n):
    return _touching_estimate(norm, n) or any(w in _span(norm, n, CLAUSE_END, 30).lower() for w in SRC_VERBS)


def draft_hedged(norm, n):
    return _touching_estimate(norm, n) or any(w in _span(norm, n, SENTENCE_END, 60).lower() for w in DRAFT_WORDS)


def dropped_hedges(text, body):
    """Numbers the source gives as an estimate at every place they appear,
    written with no estimate wording in the same sentence of the text."""
    src, src_nums = scan(body)
    draft, draft_nums = scan(text)
    out = []
    for n in _checked(draft_nums):
        if draft_hedged(draft, n) or _bound_word(draft, n):
            continue
        hits = matches(n.value, src_nums, n.kind, qualifier_of(draft, n))
        if hits and all(src_hedged(src, h) for h in hits) and n.token not in out:
            out.append(n.token)
    return out


def problems(text, body):
    """Findings for one field. A number flagged for its value or its bound is
    not flagged again for its hedge."""
    bad = ungrounded(text, body)
    bounds = dropped_bounds(text, body)
    seen = set(bad) | {x.rsplit(" ", 1)[-1] for x in bounds}
    hedges = [t for t in dropped_hedges(text, body) if t not in seen]
    return ([f"원문에 없는 숫자 '{t}'" for t in bad]
            + [f"한정어 빠짐: {x}" for x in bounds]
            + [f"추정 표현 빠짐: 원문은 '{t}'를 추정치로 전함" for t in hedges])


def problems_fields(fields, body):
    """Each field on its own: a hedge in the headline must not cover a bare
    number in the summary. Same finding in two fields is reported once."""
    out = []
    for text in fields:
        for p in problems(text, body):
            if p not in out:
                out.append(p)
    return out
