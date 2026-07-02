from vera.policy import CandidateSignal, SelectionPolicy
from vera.state import BotState


def test_selection_policy_respects_threshold_and_conflicts():
    policy = SelectionPolicy(min_score=10)
    state = type("State", (), {})()
    candidates = [
        CandidateSignal(
            merchant_id="m_1",
            category="dentists",
            merchant={"merchant_id": "m_1"},
            trigger={"kind": "renewal_due", "urgency": 4, "payload": {}},
            customer=None,
            handler_name="renewal_due",
            suppression_key="renewal:m_1",
            conversation_scope="merchant",
            priority=1,
        ),
        CandidateSignal(
            merchant_id="m_1",
            category="dentists",
            merchant={"merchant_id": "m_1"},
            trigger={"kind": "festival_upcoming", "urgency": 2, "payload": {}},
            customer=None,
            handler_name="festival_upcoming",
            suppression_key="festival:m_1",
            conversation_scope="merchant",
            priority=1,
        ),
        CandidateSignal(
            merchant_id="m_2",
            category="restaurants",
            merchant={"merchant_id": "m_2"},
            trigger={"kind": "research_digest", "urgency": 1, "payload": {}},
            customer=None,
            handler_name="research_digest",
            suppression_key="research:m_2",
            conversation_scope="merchant",
            priority=1,
        ),
    ]

    selected = policy.choose(candidates, state)

    assert len(selected) == 1
    assert selected[0].merchant_id == "m_1"
    assert selected[0].trigger["kind"] == "renewal_due"


def test_informational_trigger_is_selected_when_it_is_the_only_viable_action():
    policy = SelectionPolicy(min_score=6)
    state = BotState()
    candidates = [
        CandidateSignal(
            merchant_id="m_1",
            category="dentists",
            merchant={"merchant_id": "m_1"},
            trigger={"kind": "research_digest", "urgency": 1, "payload": {}},
            customer=None,
            handler_name="research_digest",
            suppression_key=None,
            conversation_scope="merchant",
            priority=1,
        )
    ]

    selected = policy.choose(candidates, state)

    assert [candidate.trigger["kind"] for candidate in selected] == ["research_digest"]


def test_conflict_resolution_uses_tier_and_urgency_instead_of_fixed_pairs():
    policy = SelectionPolicy(min_score=4)
    state = BotState()
    candidates = [
        CandidateSignal(
            merchant_id="m_1",
            category="dentists",
            merchant={"merchant_id": "m_1"},
            trigger={"kind": "research_digest", "urgency": 4, "payload": {}},
            customer=None,
            handler_name="research_digest",
            suppression_key=None,
            conversation_scope="merchant",
            priority=1,
        ),
        CandidateSignal(
            merchant_id="m_1",
            category="dentists",
            merchant={"merchant_id": "m_1"},
            trigger={"kind": "regulation_change", "urgency": 1, "payload": {}},
            customer=None,
            handler_name="regulation_change",
            suppression_key=None,
            conversation_scope="merchant",
            priority=1,
        ),
    ]

    decisions = policy.decide(candidates, state)
    selected = [decision["candidate"] for decision in decisions if decision["decision"] == "SEND"]
    deferred = [decision["candidate"] for decision in decisions if decision["decision"] == "DEFER"]

    assert [candidate.trigger["kind"] for candidate in selected] == ["regulation_change"]
    assert [candidate.trigger["kind"] for candidate in deferred] == ["research_digest"]


def test_defer_and_budget_limit_send_actions_per_merchant():
    policy = SelectionPolicy(min_score=4, max_actions=20, max_new_conversations_per_merchant=1)
    state = BotState()
    candidates = [
        CandidateSignal(
            merchant_id="m_1",
            category="dentists",
            merchant={"merchant_id": "m_1"},
            trigger={"kind": "renewal_due", "urgency": 4, "payload": {}},
            customer=None,
            handler_name="renewal_due",
            suppression_key=None,
            conversation_scope="merchant",
            priority=1,
        ),
        CandidateSignal(
            merchant_id="m_1",
            category="dentists",
            merchant={"merchant_id": "m_1"},
            trigger={"kind": "research_digest", "urgency": 2, "payload": {}},
            customer=None,
            handler_name="research_digest",
            suppression_key=None,
            conversation_scope="merchant",
            priority=1,
        ),
    ]

    decisions = policy.decide(candidates, state)
    send_kinds = [decision["trigger_kind"] for decision in decisions if decision["decision"] == "SEND"]
    defer_kinds = [decision["trigger_kind"] for decision in decisions if decision["decision"] == "DEFER"]

    assert send_kinds == ["renewal_due"]
    assert defer_kinds == ["research_digest"]
