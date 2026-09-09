from __future__ import annotations

import math

import pytest

from passive_agent.processors.scorer import Scorer
from passive_agent.storage.models import Item
from passive_agent.utils.config import GoalsConfig, ScoringConfig


VALID_SCORES = {
    "goal_relevance": 80,
    "novelty": 70,
    "actionability": 75,
    "difficulty_fit": 65,
    "source_quality": 85,
    "timeliness": 70,
}


class PayloadLLM:
    def __init__(self, payload: dict):
        self.payload = payload

    async def generate_json(self, system: str, user: str) -> dict:
        return self.payload


def _scorer(db, payload: dict) -> Scorer:
    return Scorer(
        PayloadLLM(payload),
        GoalsConfig(priority_topics=["Agent"]),
        ScoringConfig(),
        db,
        prompts_dir="prompts",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {key: value for key, value in VALID_SCORES.items() if key != "novelty"},
        {**VALID_SCORES, "actionability": "75"},
        {**VALID_SCORES, "difficulty_fit": True},
        {**VALID_SCORES, "source_quality": math.nan},
        {**VALID_SCORES, "timeliness": math.inf},
        {**VALID_SCORES, "goal_relevance": -1},
        {**VALID_SCORES, "goal_relevance": 101},
    ],
    ids=[
        "empty-object",
        "missing-field",
        "wrong-type",
        "bool",
        "nan",
        "infinity",
        "below-range",
        "above-range",
    ],
)
async def test_score_batch_rejects_the_whole_malformed_score_object(db, payload):
    item = Item(id="malformed-score", source="zotero", title="Malformed score")
    scorer = _scorer(db, payload)

    result = await scorer.score_batch([item])

    assert result == []
    assert item.priority_score is None
    assert db.get_all_titles() == set()
    assert db.conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 0
    assert len(scorer.errors) == 1


@pytest.mark.asyncio
async def test_score_batch_is_side_effect_free_for_valid_scores(db):
    item = Item(id="valid-score", source="zotero", title="Valid score")
    scorer = _scorer(db, VALID_SCORES)

    result = await scorer.score_batch([item])

    assert result == [item]
    assert item.priority_score == pytest.approx(75.0)
    assert len(scorer.scores) == 1
    assert scorer.scores[0].item_id == item.id
    assert db.get_all_titles() == set()
    assert db.conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 0
