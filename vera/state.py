from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .utils import normalize_text


Scope = str  # "category" | "merchant" | "customer" | "trigger"
ContextId = str


@dataclass
class StoredContext:
    version: int
    payload: dict[str, Any]


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    turns: list[dict[str, Any]] = field(default_factory=list)
    last_bot_body: Optional[str] = None
    last_bot_body_norm: Optional[str] = None
    trigger_id: Optional[str] = None
    trigger_kind: Optional[str] = None
    fallback_count: int = 0
    auto_reply_count: int = 0
    ended: bool = False

    def append_turn(self, who: str, msg: str):
        self.turns.append({"from": who, "msg": msg})

    def seen_same_auto_reply(self, msg: str) -> bool:
        if not msg:
            return False
        m = normalize_text(msg)
        recent = [normalize_text(t.get("msg", "")) for t in self.turns[-4:]]
        return recent.count(m) >= 2

    def remember_bot_message(self, body: str, trigger_id: Optional[str] = None, trigger_kind: Optional[str] = None) -> None:
        self.last_bot_body = body
        self.last_bot_body_norm = normalize_text(body)
        self.trigger_id = trigger_id
        self.trigger_kind = trigger_kind


class BotState:
    def __init__(self) -> None:
        self.contexts: dict[tuple[Scope, ContextId], StoredContext] = {}
        self.conversations: dict[str, ConversationState] = {}
        self.suppressed: dict[str, int] = {}
        self.merchant_auto_reply_count: dict[str, int] = {}
        self.merchant_last_auto_reply_norm: dict[str, str] = {}

    def reset(self) -> None:
        self.contexts.clear()
        self.conversations.clear()
        self.suppressed.clear()
        self.merchant_auto_reply_count.clear()
        self.merchant_last_auto_reply_norm.clear()

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for (scope, _), _ctx in self.contexts.items():
            counts[scope] = counts.get(scope, 0) + 1
        return counts

    def get(self, scope: Scope, context_id: ContextId) -> Optional[dict[str, Any]]:
        stored = self.contexts.get((scope, context_id))
        return stored.payload if stored else None

    def store(self, scope: Scope, context_id: ContextId, version: int, payload: dict[str, Any]) -> tuple[bool, Optional[int]]:
        key = (scope, context_id)
        cur = self.contexts.get(key)
        if cur and cur.version > version:
            return False, cur.version
        self.contexts[key] = StoredContext(version=version, payload=payload)
        return True, None

    def suppress(self, suppression_key: str) -> None:
        if not suppression_key:
            return
        self.suppressed[suppression_key] = self.suppressed.get(suppression_key, 0) + 1

    def is_suppressed(self, suppression_key: str) -> bool:
        if not suppression_key:
            return False
        return self.suppressed.get(suppression_key, 0) > 0

    def conv(self, conversation_id: str) -> ConversationState:
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = ConversationState(conversation_id=conversation_id)
        return self.conversations[conversation_id]

    def record_auto_reply(self, merchant_id: str | None, message: str) -> int:
        if not merchant_id:
            return 0
        norm = normalize_text(message or "")
        last = self.merchant_last_auto_reply_norm.get(merchant_id)
        if last != norm:
            self.merchant_last_auto_reply_norm[merchant_id] = norm
            self.merchant_auto_reply_count[merchant_id] = 1
            return 1
        self.merchant_auto_reply_count[merchant_id] = self.merchant_auto_reply_count.get(merchant_id, 0) + 1
        return self.merchant_auto_reply_count[merchant_id]

