# -*- coding: utf-8 -*-
"""What one briefing is about, read from its yaml and checked at start-up.

A briefing yaml holds everything the code used to hard-code about North
Korea: the reader, the ranking and discard rules, the desk topics, and since
P1 (docs/PLAN-email-edition.md) the sources, the reporter's role, the claim
warning for the check, the publish title and the optional tier1 slot.
audience.yaml is the North Korea briefing.

The shape is checked here, before any fetch: a typo should stop the run at
start-up, not at 07:30 halfway through the graph after the model was paid.
"""
import pathlib
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, constr

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT = HERE / "audience.yaml"

Text = constr(strip_whitespace=True, min_length=1)

class ReaderCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    누구: Text
    이미_아는_것: Text

class TopicCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    이름: Text
    데스크지침: Text
    색: constr(pattern=r"^#[0-9A-Fa-f]{6}$") = "#5F7476"

class SourceCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # no comma: NK_SKIP_SOURCES splits on it and could never switch the source off
    이름: constr(strip_whitespace=True, min_length=1, pattern=r"^[^,]+$")
    주소: constr(pattern=r"^https?://\S+$")
    # 속보: daily feeds competing for the breaking slots; 심층: weekly analysis,
    # looked back 7 days, at most one card, no competition with the news
    칸: Literal["속보", "심층"]
    # a source expected to publish every 24h: silence from it is an alarm
    # StrictBool: a quoted "false" would otherwise quietly become False or True
    매일기대: StrictBool
    # the language named to the model above a foreign body; unset, a body with
    # no Hangul in its first 500 chars is announced as 외국어
    언어: Optional[Text] = None
    # a feed that is not about the briefing only: an entry is kept when its
    # title or summary contains one of these
    키워드: list[Text] = []
    # content:encoded carries the whole article: it stands in when the page is
    # blocked. Set only after checking it is not an excerpt (graph.get_body)
    피드본문: StrictBool = False

class AudienceCfg(BaseModel):
    # extra="forbid": a misspelled key ("버릴것") would otherwise be ignored and
    # the run would go on with no discard rules at all
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    # Discord refuses a webhook username over 80 chars or containing "discord",
    # and only at publish time, after the model has been paid
    제목: constr(strip_whitespace=True, min_length=1, max_length=80)
    기자역할: Text
    주장_주의: Text
    # required even when there is none (write 1차칸: null): a deleted line must
    # not switch the MOU card off with no warning, the way a missing key used
    # to show up as DEAD. A yaml key cannot be a Python name starting with a digit.
    일차칸: Optional[Literal["통일부"]] = Field(..., alias="1차칸")
    독자: ReaderCfg
    중요도_기준: list[Text] = Field(min_length=1)
    버릴_것: list[Text]
    토픽: list[TopicCfg] = Field(min_length=1)
    소스: list[SourceCfg] = Field(min_length=1)

def load(path=DEFAULT):
    """The briefing as a plain dict (Python field names, so 1차칸 is 일차칸).
    SystemExit with one line per problem when the file is wrong."""
    path = pathlib.Path(path)
    head = f"{path.name} 오류\n  "
    try:
        cfg = AudienceCfg.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except ValidationError as exc:
        lines = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        raise SystemExit(head + "\n  ".join(lines)) from None
    for label, names in (("토픽: 이름이", [t.이름 for t in cfg.토픽]), ("소스: 이름이", [s.이름 for s in cfg.소스]),
                         ("소스 주소: 같은 주소가", [s.주소 for s in cfg.소스])):
        if len(names) != len(set(names)):
            raise SystemExit(head + f"{label} 겹침")
    if "discord" in cfg.제목.lower():            # pydantic's regex has no look-ahead
        raise SystemExit(head + "제목: 'discord'가 들어간 이름은 디스코드가 거절함")
    if any(s.이름 == "통일부" for s in cfg.소스):
        # the tier1 card is counted under 통일부 in metrics and the scorecard
        raise SystemExit(head + "소스: 이름 '통일부'는 1차칸 몫이라 쓸 수 없음")
    if not any(s.칸 == "속보" for s in cfg.소스):
        # every source 심층 would leave the breaking slots empty every day, quietly
        raise SystemExit(head + "소스: 칸이 속보인 소스가 하나도 없음")
    return cfg.model_dump()
