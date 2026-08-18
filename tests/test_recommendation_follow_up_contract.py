"""The existing recommendation chips remain the one UI path for follow-ups."""

from __future__ import annotations

import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_chip_click_sends_the_exact_suggestion_as_the_next_message() -> None:
    source = (ROOT / "frontend/src/features/recommend/AgentTurnView.tsx").read_text(encoding="utf-8")

    assert "onClick={() => onSendSuggestion(suggestion)}" in source
    assert 'data-testid="agent-follow-ups"' in source


def test_live_and_restored_briefs_share_the_same_chip_normalizer() -> None:
    source = (ROOT / "frontend/src/pages/Recommend.tsx").read_text(encoding="utf-8")

    assert source.count("normalizeBriefFollowUps(") >= 3  # definition + live polling + restore
    assert "!values.includes(suggestion)" in source
    assert ".slice(0, 80)" in source
    assert "values.length >= 4" in source


def test_aborted_failed_and_clarification_turns_hide_answer_and_chips() -> None:
    view = (ROOT / "frontend/src/features/recommend/AgentTurnView.tsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/pages/Recommend.tsx").read_text(encoding="utf-8")

    assert view.count("!turn.aborted && !turn.failed && !turn.question") >= 2
    assert "Boolean(turn.answer.trim())" in view
    assert "answer: ''" in page
    assert "followUps: []" in page


def test_history_restore_uses_persisted_agent_brief_and_does_not_regenerate_chips() -> None:
    source = (ROOT / "frontend/src/pages/Recommend.tsx").read_text(encoding="utf-8")
    restore_branch = source.split("messageType === 'agent_brief'", 2)[-1]

    assert "payload.brief as RecommendationAgentBrief" in restore_branch
    assert "normalizeBriefFollowUps" in restore_branch
    assert "resumeTurnIds.push(turn.turnId)" in source
