import asyncio

from bot import STATE, TickBody, tick
from vera.composer import compose
from vera.intents import PLANNING, REMINDER, SEASONAL, trigger_intent
from vera.policy import CandidateSignal, SelectionPolicy


def _category(slug="clinics"):
    return {
        "slug": slug,
        "peer_stats": {"avg_ctr": 0.03},
        "trend_signals": [{"query": "weekend family package", "delta_yoy": 0.31}],
        "seasonal_beats": [{"month_range": "Oct-Nov", "note": "festival family bookings"}],
    }


def _merchant(category_slug="clinics"):
    return {
        "merchant_id": "m_unseen",
        "category_slug": category_slug,
        "identity": {"name": "CarePlus Clinic", "owner_first_name": "Anita", "city": "Pune", "locality": "Aundh", "languages": ["en"]},
        "subscription": {"status": "active", "plan": "Pro", "days_remaining": 9},
        "performance": {"views": 1440, "calls": 21, "ctr": 0.018, "leads": 8},
        "offers": [{"status": "active", "title": "Family Health Check @ Rs499"}],
        "customer_aggregate": {"repeat_customer_pct": 0.42, "lapsed_180d_plus": 33},
        "signals": ["ctr_below_peer_median", "active_planning"],
        "review_themes": [{"theme": "front_desk_wait", "occurrences_30d": 4}],
        "conversation_history": [
            {"from": "merchant", "body": "Can we launch a 4-week family health package at Rs499?", "engagement": "intent_planning"}
        ],
    }


def test_unknown_seasonal_trigger_maps_to_seasonal_intent_and_uses_proof():
    trigger = {
        "kind": "holiday_campaign",
        "scope": "merchant",
        "payload": {"event_name": "Dussehra weekend", "event_date": "2026-10-20"},
        "suppression_key": "holiday:test",
        "urgency": 2,
    }

    result = compose(_category(), _merchant(), trigger, None)

    assert trigger_intent(trigger, _merchant(), _category()) == SEASONAL
    assert "Dussehra weekend" in result.body
    assert "Family Health Check @ Rs499" in result.body
    assert result.cta == "binary_yes_stop"


def test_unknown_planning_trigger_reuses_conversation_history():
    trigger = {
        "kind": "campaign_planning",
        "scope": "merchant",
        "payload": {"campaign": "family health package"},
        "suppression_key": "planning:test",
        "urgency": 4,
    }

    result = compose(_category(), _merchant(), trigger, None)

    assert trigger_intent(trigger, _merchant(), _category()) == PLANNING
    assert "4-week family health package at Rs499" in result.body
    assert "1440 views" in result.body
    assert result.template_name == "vera_planning_intent_v1"


def test_unknown_customer_reminder_without_customer_stays_merchant_facing():
    trigger = {
        "kind": "appointment_due",
        "scope": "customer",
        "customer_id": "c_missing",
        "payload": {"due_date": "2026-08-15", "available_slots": [{"label": "Fri 6pm"}]},
        "suppression_key": "appointment:test",
        "urgency": 3,
    }

    result = compose(_category(), _merchant(), trigger, None)

    assert trigger_intent(trigger, _merchant(), _category()) == REMINDER
    assert result.send_as == "vera"
    assert "customer-safe reminder" in result.body
    assert "Hi there" not in result.body


def test_tick_skips_customer_trigger_when_customer_context_is_missing():
    STATE.reset()
    category = _category()
    merchant = _merchant()
    trigger = {
        "id": "trg_missing_customer",
        "kind": "appointment_due",
        "scope": "customer",
        "merchant_id": merchant["merchant_id"],
        "customer_id": "c_missing",
        "payload": {"due_date": "2026-08-15"},
        "suppression_key": "appointment:missing",
        "urgency": 5,
    }
    STATE.store("category", category["slug"], 1, category)
    STATE.store("merchant", merchant["merchant_id"], 1, merchant)
    STATE.store("trigger", trigger["id"], 1, trigger)

    response = asyncio.run(tick(TickBody(now="2026-07-02T00:00:00Z", available_triggers=[trigger["id"]])))

    assert response == {"actions": []}


def test_priority_score_works_for_unknown_high_urgency_trigger_with_features():
    policy = SelectionPolicy(min_score=6)
    state = type("State", (), {})()
    candidate = CandidateSignal(
        merchant_id="m_unseen",
        category="clinics",
        merchant=_merchant(),
        trigger={"kind": "urgent_profile_gap", "urgency": 5, "payload": {"deadline_iso": "2026-08-01", "profile_field": "hours"}},
        suppression_key=None,
    )

    selected = policy.choose([candidate], state)

    assert selected == [candidate]
    assert policy._score_candidate(candidate, state).total >= 6


def test_supply_alert_uses_only_payload_and_source_facts():
    category = {
        "slug": "pharmacies",
        "digest": [
            {
                "id": "d_alert",
                "title": "Atorvastatin voluntary recall",
                "source": "CDSCO alert 2026-04",
                "actionable": "Check shelf stock and notify affected refill customers",
            }
        ],
        "peer_stats": {"avg_ctr": 0.04},
    }
    merchant = _merchant("pharmacies")
    merchant["identity"]["name"] = "Apollo Health Plus Pharmacy"
    merchant["customer_aggregate"] = {"chronic_rx_count": 240, "repeat_customer_pct": 0.68}
    trigger = {
        "kind": "supply_alert",
        "scope": "merchant",
        "payload": {
            "alert_id": "d_alert",
            "molecule": "atorvastatin",
            "manufacturer": "MfrZ",
            "affected_batches": ["AT2024-1102", "AT2024-1108"],
        },
        "suppression_key": "supply:test",
        "urgency": 5,
    }

    result = compose(category, merchant, trigger, None)

    assert "Source: CDSCO alert 2026-04" in result.body
    assert "atorvastatin" in result.body
    assert "AT2024-1102" in result.body
    assert "chronic Rx customer count is 240" in result.body
    assert "1.0 mSv" not in result.body
    assert "RVG" not in result.body


def test_merchant_proof_is_not_machine_labeled_context():
    result = compose(
        _category("restaurants"),
        _merchant("restaurants"),
        {"kind": "holiday_campaign", "scope": "merchant", "payload": {"event_name": "long weekend"}, "suppression_key": "proof:test"},
        None,
    )

    assert "Context:" not in result.body
    assert "For your store:" in result.body
    assert "active offer:" not in result.body
