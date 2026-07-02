from __future__ import annotations

import re
import time
from typing import Any, Literal, Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, ValidationError
from starlette.responses import JSONResponse

from vera.composer import compose
from vera.policy import CandidateSignal, SelectionPolicy
from vera.state import BotState
from vera.utils import apply_language, classify_reply, detect_language, utcnow_iso


app = FastAPI()
START = time.time()
STATE = BotState()
SELECTION_POLICY = SelectionPolicy(min_score=6, max_actions=20)


# -----------------------------
# Models (match test brief)
# -----------------------------


class ContextPush(BaseModel):
    scope: Literal["category", "merchant", "customer", "trigger"]
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str | None = None


class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = Field(default_factory=list)


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: Literal["merchant", "customer"]
    message: str
    received_at: str
    turn_number: int


# -----------------------------
# Endpoints
# -----------------------------


@app.get("/v1/healthz")
async def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START),
        "contexts_loaded": STATE.counts(),
    }


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Local Candidate",
        "team_members": ["Kripakara M N"],
        "model": "deterministic_rules_v1",
        "approach": "deterministic router + grounded templates by trigger.kind + suppression + auto-reply/intent handling",
        "contact_email": "local@example.com",
        "version": "0.1.0",
        "submitted_at": "2026-05-03T00:00:00Z",
    }


@app.post("/v1/context")
async def push_context(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_payload", "details": "request body must be valid JSON"},
        )

    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_payload", "details": "request body must be a JSON object"},
        )

    scope = payload.get("scope")
    if scope not in {"category", "merchant", "customer", "trigger"}:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_scope", "details": "scope must be one of category, merchant, customer, trigger"},
        )

    try:
        body = ContextPush(**payload)
    except ValidationError as exc:
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": "invalid_payload", "details": str(exc)},
        )

    accepted, current_version = STATE.store(body.scope, body.context_id, body.version, body.payload)
    if not accepted:
        # Spec expects HTTP 409 on stale version.
        return JSONResponse(
            status_code=409,
            content={"accepted": False, "reason": "stale_version", "current_version": current_version},
        )
    return JSONResponse(
        status_code=200,
        content={"accepted": True, "ack_id": f"ack_{body.context_id}_v{body.version}", "stored_at": utcnow_iso()},
    )


@app.post("/v1/tick")
async def tick(body: TickBody):
    actions: list[dict[str, Any]] = []
    candidates: list[CandidateSignal] = []

    for trg_id in body.available_triggers[:20]:
        trg = STATE.get("trigger", trg_id)
        if not trg:
            continue

        suppression_key = str(trg.get("suppression_key") or "")
        if suppression_key and STATE.is_suppressed(suppression_key):
            continue

        merchant_id = trg.get("merchant_id")
        if not merchant_id:
            continue
        merchant = STATE.get("merchant", merchant_id)
        if not merchant:
            continue
        category_slug = merchant.get("category_slug") or merchant.get("category") or None
        if not category_slug:
            continue
        category = STATE.get("category", str(category_slug))
        if not category:
            continue

        customer_id = trg.get("customer_id")
        customer = STATE.get("customer", customer_id) if customer_id else None
        if customer_id and not customer:
            continue

        candidates.append(
            CandidateSignal(
                merchant_id=merchant_id,
                category=str(category_slug),
                merchant=merchant,
                trigger=trg,
                customer=customer,
                handler_name=str(trg.get("kind") or "unknown"),
                suppression_key=suppression_key or None,
                conversation_scope="customer" if customer_id else "merchant",
                priority=int(trg.get("urgency") or 0),
            )
        )

    selected_candidates = SELECTION_POLICY.choose(candidates, STATE)

    for candidate in selected_candidates:
        trg = candidate.trigger or {}
        trg_id = str(trg.get("id") or "")
        merchant_id = str(candidate.merchant_id)
        merchant = candidate.merchant or {}
        category = STATE.get("category", str(candidate.category or "")) if candidate.category else None
        customer = candidate.customer
        if not category:
            continue

        composed = compose(category=category, merchant=merchant, trigger=trg, customer=customer)

        now_compact = re.sub(r"[^0-9A-Za-z]+", "", body.now)[:24] or "now"
        conv_id = f"conv_{merchant_id}_{trg_id}_{now_compact}"

        if composed.suppression_key:
            STATE.suppress(composed.suppression_key)

        conv = STATE.conv(conv_id)
        conv.merchant_id = merchant_id
        conv.customer_id = customer.get("customer_id") if isinstance(customer, dict) else None
        conv.remember_bot_message(composed.body, trigger_id=trg_id, trigger_kind=trg.get("kind"))

        actions.append(
            {
                "conversation_id": conv_id,
                "merchant_id": merchant_id,
                "customer_id": customer.get("customer_id") if isinstance(customer, dict) else None,
                "send_as": composed.send_as,
                "trigger_id": trg_id,
                "template_name": composed.template_name,
                "template_params": composed.template_params,
                "body": composed.body,
                "cta": composed.cta,
                "suppression_key": composed.suppression_key,
                "rationale": composed.rationale,
            }
        )

    return {"actions": actions}


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    conv = STATE.conv(body.conversation_id)
    if conv.ended:
        return {"action": "end", "rationale": "Conversation already ended."}

    conv.merchant_id = conv.merchant_id or body.merchant_id
    conv.customer_id = conv.customer_id or body.customer_id
    conv.append_turn(body.from_role, body.message)

    cls = classify_reply(body.message)
    lang = detect_language(body.message)

    def loc(text: str) -> str:
        return apply_language(text, lang) if lang else text

    # 1) Opt-out / hostile → end immediately
    if cls == "opt_out":
        conv.ended = True
        return {"action": "end", "rationale": "Opt-out/hostile reply detected; ending conversation and suppressing further outreach."}

    # 2) Auto-reply: judge may change conversation_id each turn, so track per merchant too.
    if cls == "auto_reply" or conv.seen_same_auto_reply(body.message):
        count = STATE.record_auto_reply(body.merchant_id, body.message)
        conv.auto_reply_count += 1
        # First: one explicit nudge for owner
        if count == 1:
            return {
                "action": "send",
                "body": loc("Looks like an auto-reply. When the owner/manager sees this, just reply YES and I'll send the draft."),
                "cta": "binary_yes_stop",
                "rationale": "Detected WhatsApp Business auto-reply; one explicit low-friction prompt for the owner.",
            }
        # Second: back off
        if count == 2:
            return {"action": "wait", "wait_seconds": 14400, "rationale": "Auto-reply repeated; backing off 4 hours for a real human reply."}
        # Third+: end
        conv.ended = True
        return {"action": "end", "rationale": "Auto-reply repeated multiple times; no engagement signal, closing conversation to avoid pollution."}

    # 3) Commitment intent (“ok lets do it”) → switch to action
    if cls == "commit":
        return {
            "action": "send",
            "body": loc("Done — I'll draft it now. Quick confirm: should I write it in simple English or Hindi-English mix?"),
            "cta": "open_ended",
            "rationale": "Explicit commitment detected; switching from qualifying to execution with one minimal clarification that improves fit.",
        }

    # Default: acknowledge + offer next step without inventing anything
    topic = "the original topic"
    if conv.trigger_kind == "recall_due":
        topic = "the recall reminder"
    elif conv.trigger_kind in {"research_digest", "regulation_change", "festival_upcoming", "curious_ask_due", "active_planning_intent"}:
        topic = "the update we just discussed"
    elif conv.trigger_kind in {"perf_dip", "perf_spike", "milestone_reached", "review_theme_emerged", "competitor_opened", "renewal_due", "winback_eligible", "gbp_unverified"}:
        topic = "the next step for the merchant signal"
    elif conv.trigger_kind in {"wedding_package_followup"}:
        topic = "the wedding follow-up"

    if conv.fallback_count == 0:
        body = loc(f"Got it. We were talking about {topic}. If you want, I can turn that into a concrete draft or a short next step.")
    else:
        body = loc(f"Understood. I can keep this focused on {topic} and help with the next concrete step if that’s useful.")

    conv.fallback_count += 1
    conv.remember_bot_message(body, trigger_id=conv.trigger_id, trigger_kind=conv.trigger_kind)
    return {
        "action": "send",
        "body": body,
        "cta": "open_ended",
        "rationale": "Keeps the conversation anchored to the original trigger and avoids repeating the same generic fallback.",
    }


@app.post("/v1/teardown")
async def teardown():
    """
    Optional endpoint mentioned in the testing brief.
    Useful for local judge runs without restarting the server.
    """
    STATE.reset()
    return {"ok": True, "stored_at": utcnow_iso()}
