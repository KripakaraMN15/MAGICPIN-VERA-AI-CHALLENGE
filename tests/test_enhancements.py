from vera.composer import compose
from vera.policy import CandidateSignal, SelectionPolicy
from vera.utils import apply_category_voice, pick_language


def test_language_adaptation_uses_localized_cta_and_acknowledgement():
    category = {"slug": "dentists"}
    merchant = {
        "merchant_id": "m_1",
        "category_slug": "dentists",
        "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera", "languages": ["en", "hi"], "city": "Delhi"},
        "offers": [{"status": "active", "title": "Dental Cleaning @ ₹299"}],
    }
    trigger = {"kind": "research_digest", "suppression_key": "research:test", "payload": {"top_item_id": "d_1"}}
    customer = {"identity": {"name": "Priya", "language_pref": "hi-en mix"}}

    result = compose(category=category, merchant=merchant, trigger=trigger, customer=customer)

    assert "Ek" in result.body or "draft" in result.body.lower()
    assert "Want" not in result.body


def test_category_voice_replaces_only_allowed_terms():
    voice = {
        "preferred_tone": "peer_clinical",
        "vocab_allowed": ["check-up", "recall", "oral care"],
        "taboo": ["cheap", "discount"],
    }

    text = "Get a cheap checkup today - discount offer!"
    transformed = apply_category_voice(text, voice)

    assert "check-up" in transformed, "checkup should be replaced with check-up"
    assert "cheap" not in transformed, "taboo word cheap should be removed"
    assert "discount" not in transformed, "taboo word discount should be removed"


def test_priority_score_adds_contextual_bonuses():
    policy = SelectionPolicy(min_score=4)
    state = type("State", (), {})()
    candidate = CandidateSignal(
        merchant_id="m_1",
        category="dentists",
        merchant={
            "merchant_id": "m_1",
            "category_slug": "dentists",
            "signals": ["ctr_below_peer_median"],
            "review_themes": ["waiting time"],
            "customer_aggregate": {"retention_6mo_pct": 0.38},
            "performance": {"ctr": 0.012},
        },
        trigger={"kind": "perf_dip", "urgency": 4, "payload": {"metric": "CTR", "delta_pct": -0.15}},
        customer={"customer_id": "c_1"},
    )

    score = policy._score_candidate(candidate, state)

    assert score.peer_gap_bonus >= 1
    assert score.merchant_signal_bonus >= 1
    assert score.customer_readiness_bonus >= 1


def test_composer_uses_peer_stats_and_signal_context_when_available():
    category = {"slug": "dentists", "peer_stats": {"avg_ctr": 0.03}}
    merchant = {
        "merchant_id": "m_1",
        "category_slug": "dentists",
        "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera"},
        "performance": {"views": 100, "calls": 6, "ctr": 0.01, "delta_7d": {"views_pct": -0.1, "calls_pct": -0.2}},
        "signals": ["ctr_below_peer_median"],
        "review_themes": ["waiting time"],
    }
    trigger = {"kind": "perf_dip", "suppression_key": "perf:test", "payload": {"metric": "CTR", "delta_pct": -0.15}}

    result = compose(category=category, merchant=merchant, trigger=trigger, customer=None)

    assert "category median" in result.body.lower() or "peer" in result.body.lower()


def test_composer_omits_unavailable_context_without_hallucinating():
    category = {"slug": "dentists"}
    merchant = {"merchant_id": "m_1", "category_slug": "dentists", "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera"}}
    trigger = {"kind": "festival_upcoming", "suppression_key": "fest:test", "payload": {"festival": "Diwali", "days_until": 7, "date": "2026-10-24"}}

    result = compose(category=category, merchant=merchant, trigger=trigger, customer=None)

    assert "Diwali" in result.body
    assert "100%" not in result.body
    assert "unknown" not in result.body.lower()


def test_suppression_still_blocks_candidates():
    policy = SelectionPolicy(min_score=4)
    state = type("State", (), {})()
    state.is_suppressed = lambda key: key == "suppressed"
    candidates = [
        CandidateSignal(merchant_id="m_1", category="dentists", merchant={}, trigger={"kind": "research_digest", "urgency": 2, "payload": {}}, suppression_key="suppressed"),
        CandidateSignal(merchant_id="m_2", category="dentists", merchant={}, trigger={"kind": "renewal_due", "urgency": 4, "payload": {}}, suppression_key=None),
    ]

    decisions = policy.decide(candidates, state)
    sent = [d["trigger_kind"] for d in decisions if d["decision"] == "SEND"]

    assert sent == ["renewal_due"]


def test_decision_ordering_remains_deterministic_for_equal_scores():
    policy = SelectionPolicy(min_score=4)
    state = type("State", (), {})()
    candidates = [
        CandidateSignal(merchant_id="m_2", category="dentists", merchant={}, trigger={"kind": "research_digest", "urgency": 1, "payload": {}}, suppression_key=None),
        CandidateSignal(merchant_id="m_1", category="dentists", merchant={}, trigger={"kind": "research_digest", "urgency": 1, "payload": {}}, suppression_key=None),
    ]

    decisions = policy.decide(candidates, state)
    sent = [d["merchant_id"] for d in decisions if d["decision"] == "SEND"]

    assert sent == ["m_1", "m_2"]
