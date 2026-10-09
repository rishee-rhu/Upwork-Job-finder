import json
from types import SimpleNamespace

from findjobs import judge as jmod

from .test_pipeline import judgment


class FakeMessages:
    def __init__(self, payload, stop="end_turn"):
        self.payload, self.stop, self.calls = payload, stop, []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def _judge(profile, payload, stop="end_turn"):
    j = jmod.ApiJudge.__new__(jmod.ApiJudge)
    j.profile, j.model, j.effort, j.workers = profile, jmod.MODEL, "medium", 2
    j.system = [{"type": "text", "text": "x"}]
    j.client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(payload, stop)))
    return j


def test_api_judge_request_shape_and_clamp(profile, mk):
    j = _judge(profile, judgment(direct_match=99))
    out = j.judge([mk(1)])
    (v,) = out.values()
    assert v["direct_match"] == 20
    call = j.client.beta.messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"


def test_api_judge_refusal_becomes_error(profile, mk):
    j = _judge(profile, {}, stop="refusal")
    (v,) = j.judge([mk(1)]).values()
    assert "error" in v


def test_schema_requires_every_field():
    assert set(jmod.JUDGMENT_SCHEMA["required"]) == set(jmod.JUDGMENT_SCHEMA["properties"])
    assert set(jmod.PROFILE_SCHEMA["required"]) == set(jmod.PROFILE_SCHEMA["properties"])
