import os

import pytest

from clauseanchor.model import OpenAICompatModel
from clauseanchor.pipeline import review_text

pytestmark = pytest.mark.skipif(
    os.environ.get("CLAUSEANCHOR_LIVE") != "1", reason="set CLAUSEANCHOR_LIVE=1 to call a model"
)


@pytest.mark.live
def test_live_model_review_returns_a_result_for_every_issue(playbook, sample_text):
    result = review_text(sample_text, "live", playbook, OpenAICompatModel.from_env())
    assert len(result.results) == len(playbook.issues)
