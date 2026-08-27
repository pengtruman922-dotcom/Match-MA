"""推荐会话的买家锚点：会话记不记得这一轮是给谁做的。

在这之前会话永远是匿名的，`buyer_party_fact_block()` 因此在生产里恒返回空串
—— 函数写好了、测试齐了、注释里点名「与现有业务有关联性」「强链补链」是它存在
的理由，但**唯一的调用点没传 id**。这类缺陷不报错、不掉测试，只是让模型少看见
一半输入，所以这里的重点是钉住调用点本身。
"""

from __future__ import annotations

import inspect
import re
from uuid import uuid4

import pytest

from backend.app.api.routes.recommendations import RecommendationAgentTurnRequest


def test_an_anonymous_turn_is_still_valid() -> None:
    """不传锚点必须和从前完全一样 —— 纯对话页是它的主场景。"""
    request = RecommendationAgentTurnRequest(mode="buyer_to_target", user_message="找华东食品加工标的")

    assert request.buyer_intent_id is None


def test_a_turn_can_carry_the_buyer_intent_it_is_made_for() -> None:
    intent_id = uuid4()
    request = RecommendationAgentTurnRequest(
        mode="buyer_to_target",
        user_message="找华东食品加工标的",
        buyer_intent_id=str(intent_id),
    )

    assert request.buyer_intent_id == intent_id


def test_the_deep_eval_call_site_passes_the_buyer_party() -> None:
    """深评的 `buyer_party_id` 有默认值 None —— 漏传它没有任何症状。

    这正是它此前恒为空的原因：参数在签名里、fact block 在服务层、两端都有测试，
    中间那一行没接上，而没有任何一条用例看得见「调用点传了没有」。所以在这里做
    成静态断言：handler 里调 `run_recommendation_deep_eval` 必须显式传这个参数。
    """
    from backend.app.jobs.handlers import recommendation as handler

    source = inspect.getsource(handler)
    call = re.search(r"run_recommendation_deep_eval\(\s*db,(.*?)\n        \),", source, re.S)
    assert call is not None, "找不到 run_recommendation_deep_eval 的调用点"
    assert "buyer_party_id=" in call.group(1), (
        "深评调用点没传 buyer_party_id —— 买方自身情况会恒为空，"
        "而这不会报错、不会掉别的测试"
    )


def test_the_anchor_is_read_from_the_session_row_not_the_job_payload() -> None:
    """锚点可以在开聊之后才挂上，而 payload 是入队那一刻冻结的。"""
    from backend.app.jobs.handlers import recommendation as handler

    source = inspect.getsource(handler)
    assert "session_anchor_buyer_party_id(db, session_id)" in source


class _FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeDb:
    def __init__(self, rowcount: int = 1) -> None:
        self.statements: list[str] = []
        self.params: list[dict] = []
        self._rowcount = rowcount

    def execute(self, statement, params):
        self.statements.append(str(statement))
        self.params.append(params)
        return _FakeResult(self._rowcount)


def test_attaching_an_anchor_only_fills_an_empty_one() -> None:
    """换锚点等于这一轮之前的回答换了买家却不留痕迹，所以只补空的。"""
    from backend.app.services.recommendation_flow import attach_session_anchor

    db = _FakeDb(rowcount=1)
    written = attach_session_anchor(
        db, session_id=uuid4(), buyer_intent_id=uuid4(), buyer_party_id=uuid4()
    )

    assert written is True
    assert "buyer_intent_id is null" in db.statements[0]


def test_attaching_reports_when_the_session_was_already_anchored() -> None:
    from backend.app.services.recommendation_flow import attach_session_anchor

    db = _FakeDb(rowcount=0)
    written = attach_session_anchor(
        db, session_id=uuid4(), buyer_intent_id=uuid4(), buyer_party_id=None
    )

    assert written is False


def test_a_null_party_never_erases_one_the_session_already_had() -> None:
    """需求可能还没关联主体，那时补写不能把会话上已有的主体抹掉。"""
    from backend.app.services.recommendation_flow import attach_session_anchor

    db = _FakeDb()
    attach_session_anchor(db, session_id=uuid4(), buyer_intent_id=uuid4(), buyer_party_id=None)

    assert "coalesce(:buyer_party_id, buyer_party_id)" in db.statements[0]


def test_the_anchor_query_falls_back_to_the_intents_party() -> None:
    """前端锚定时给的是需求 id，主体是推导出来的。"""
    from backend.app.services.recommendation_flow import session_anchor_buyer_party_id

    class _Db:
        def execute(self, statement, params):
            self.statement = str(statement)
            outer = self

            class _Result:
                def mappings(self):
                    return self

                def one_or_none(self):
                    return {"buyer_party_id": None}

            return _Result()

    db = _Db()
    session_anchor_buyer_party_id(db, uuid4())

    assert "coalesce(rs.buyer_party_id, bi.buyer_party_id)" in db.statement


def test_the_route_checks_the_intent_is_visible_before_using_it() -> None:
    """传一个别人的需求 id 就能把别人的买家资料读进自己这一轮 —— 必须先判可见。"""
    from backend.app.api.routes import recommendations as route

    source = inspect.getsource(route.create_recommendation_agent_turn)
    guard = source.find("ensure_entity_visible")
    use = source.find("_get_buyer_party_id_for_intent")
    assert guard != -1, "锚点没有可见性检查"
    assert guard < use, "可见性检查必须发生在读取主体之前"
