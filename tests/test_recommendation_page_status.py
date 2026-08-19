from uuid import UUID, uuid4

from backend.app.api.authn import AuthContext
from backend.app.services.recommendation_flow import (
    _build_recommendation_agent_status,
    _filter_recommendation_session_summaries,
    _list_recommendation_session_overview_rows,
    _optional_uuid,
    _recommendation_page_overview,
    _recommendation_session_display,
    _recommendation_session_is_processing,
)

SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
BUYER_INTENT_ID = UUID("00000000-0000-0000-0000-000000000002")
SELLER_TARGET_ID = UUID("00000000-0000-0000-0000-000000000003")


def test_recommendation_session_display_for_buyer_to_target() -> None:
    display = _recommendation_session_display(
        {
            "id": SESSION_ID,
            "mode": "buyer_to_target",
            "buyer_intent_id": BUYER_INTENT_ID,
            "buyer_intent_name": "Healthcare consolidation need",
            "buyer_name": "Zhejiang SOE",
            "seller_target_id": None,
        }
    )

    assert display["title"] == "Healthcare consolidation need"
    assert display["anchor"] == {"entity_type": "buyer_intent", "entity_id": str(BUYER_INTENT_ID)}
    assert display["primary_action"] == "recommend_targets"


def test_recommendation_session_display_for_target_to_buyer() -> None:
    display = _recommendation_session_display(
        {
            "id": SESSION_ID,
            "mode": "target_to_buyer",
            "buyer_intent_id": None,
            "seller_target_id": SELLER_TARGET_ID,
            "seller_target_name": "Hangzhou Device Target",
        }
    )

    assert display["title"] == "Hangzhou Device Target"
    assert display["anchor"] == {"entity_type": "seller_target", "entity_id": str(SELLER_TARGET_ID)}
    assert display["primary_action"] == "recommend_buyers"


def test_processing_and_page_overview_counts() -> None:
    # 驱动源随拆除逐层换过：rerank_status（5A 删）→ report_status（5B 删）→ agent_status。
    # 判据本身没有变过，断言也没有跟着改。
    processing_summary = {"agent_status": {"status": "running"}}
    idle_summary = {"agent_status": {"status": "completed"}}

    overview = _recommendation_page_overview([processing_summary, idle_summary], [processing_summary])

    assert _recommendation_session_is_processing(processing_summary) is True
    assert _recommendation_session_is_processing(idle_summary) is False
    assert overview["recent_session_count"] == 2
    assert overview["running_session_count"] == 1


def test_agent_brief_without_answer_keeps_session_processing_until_writer_lands() -> None:
    messages = [
        {"role": "user", "metadata_json": {"turn_id": "turn-1", "message_type": "agent_user_message"}},
        {"role": "tool", "metadata_json": {"turn_id": "turn-1", "message_type": "agent_brief"}},
    ]
    status = _build_recommendation_agent_status(None, session_id=SESSION_ID, messages=messages)
    summary = {"agent_status": status}

    assert status == {"status": "writing", "turn_id": "turn-1", "writer_pending": True}
    assert _recommendation_session_is_processing(summary) is True

    messages.append(
        {"role": "assistant", "metadata_json": {"turn_id": "turn-1", "message_type": "agent_answer"}}
    )
    completed = _build_recommendation_agent_status(None, session_id=SESSION_ID, messages=messages)
    summary["agent_status"] = completed

    assert completed["status"] == "completed"
    assert _recommendation_session_is_processing(summary) is False


def test_recommendation_session_filter_runs_off_the_same_yellow_dot_judgement() -> None:
    # failed / generated / selected 三个取值随推荐报告与选中一起下线（阶段五 5B），
    # 剩下的 running / idle 与黄点判据同源，所以两者永远不会互相矛盾。
    running_summary = {"agent_status": {"status": "running"}}
    writing_summary = {"agent_status": {"status": "writing", "writer_pending": True}}
    idle_summary = {"agent_status": {"status": "completed"}}

    summaries = [running_summary, writing_summary, idle_summary]

    assert _filter_recommendation_session_summaries(summaries, "running") == [
        running_summary,
        writing_summary,
    ]
    assert _filter_recommendation_session_summaries(summaries, "idle") == [idle_summary]
    assert _filter_recommendation_session_summaries(summaries, "all") == summaries
    assert _filter_recommendation_session_summaries(summaries, None) == summaries


def test_optional_uuid_accepts_uuid_and_string() -> None:
    assert _optional_uuid(SELLER_TARGET_ID) == SELLER_TARGET_ID
    assert _optional_uuid(str(SELLER_TARGET_ID)) == SELLER_TARGET_ID
    assert _optional_uuid("not-a-uuid") is None


class _MessageResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_MessageResult":
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _OverviewDb:
    def __init__(self) -> None:
        self.statement = ""
        self.params: dict = {}

    def execute(self, statement, params) -> _MessageResult:
        self.statement = str(statement)
        self.params = params
        return _MessageResult([])


def test_recommendation_history_search_is_scoped_and_mode_specific() -> None:
    current_user = AuthContext(user_id=uuid4(), role="consultant", name="consultant")
    db = _OverviewDb()

    rows = _list_recommendation_session_overview_rows(
        db,
        current_user=current_user,
        mode=None,
        limit=20,
        offset=0,
        q="  医疗  ",
    )

    assert rows == []
    assert "rs.created_by = :scope_user_id" in db.statement
    assert "rs.mode = 'buyer_to_target'" in db.statement
    assert "coalesce(bi.intent_name, '') ilike :q" in db.statement
    assert "rs.mode = 'target_to_buyer'" in db.statement
    assert "coalesce(st.target_name, '') ilike :q" in db.statement
    assert "left join app_user creator on creator.id = rs.created_by" in db.statement
    assert "creator.username" in db.statement
    assert db.params["scope_user_id"] == current_user.user_id
    assert db.params["q"] == "%医疗%"


# -- Agent 会话在「最近推荐」里必须彼此可辨 --------------------------------


def _agent_session(first_message: str) -> dict:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "mode": "buyer_to_target",
        "metadata_json": {"temporary_filter": True},
        "initial_condition_snapshot_json": {"agent_session": True, "first_message": first_message},
        "anonymous_input_snapshot": first_message,
    }


def _turn_messages(count: int) -> list[dict]:
    return [{"metadata_json": {"turn_id": f"t{index}"}} for index in range(count)]


def test_agent_session_is_titled_by_its_opening_question() -> None:
    display = _recommendation_session_display(
        _agent_session("客户想收华东的精密制造"),
        messages=_turn_messages(2),
    )

    assert display["title"] == "客户想收华东的精密制造"
    assert display["subtitle"] == "2 轮对话"
    assert display["primary_action"] == "agent_chat"


def test_long_opening_questions_are_elided_not_dropped() -> None:
    display = _recommendation_session_display(_agent_session("需求" * 40), messages=[])

    assert display["title"].endswith("…")
    assert len(display["title"]) == 25


def test_agent_session_route_points_at_the_chat_page() -> None:
    display = _recommendation_session_display(_agent_session("找标的"), messages=[])

    assert display["route"].startswith("/recommend?session=")


def test_legacy_temporary_filter_sessions_keep_their_old_label() -> None:
    display = _recommendation_session_display(
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "mode": "buyer_to_target",
            "metadata_json": {"temporary_filter": True},
            "initial_condition_snapshot_json": {},
        }
    )

    assert display["title"] == "临时条件筛选"
    assert display["anchor"] == {"entity_type": None, "entity_id": None}
    assert display["primary_action"] == "temporary_filter"
