import json
import asyncio

from bot import STATE, push_context


class DummyRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def test_context_invalid_scope_returns_structured_error():
    STATE.reset()

    response = asyncio.run(push_context(DummyRequest({"scope": "invalid", "context_id": "x", "version": 1, "payload": {}})))

    assert response.status_code == 400
    assert json.loads(response.body.decode("utf-8")) == {
        "accepted": False,
        "reason": "invalid_scope",
        "details": "scope must be one of category, merchant, customer, trigger",
    }
