from __future__ import annotations

from typing import Any

from .utils import normalize_text, safe_get


Intent = str

RETENTION: Intent = "retention"
REMINDER: Intent = "reminder"
SEASONAL: Intent = "seasonal"
PLANNING: Intent = "planning"
INSIGHT: Intent = "insight"
PERFORMANCE: Intent = "performance"
REPUTATION: Intent = "reputation"
COMPETITION: Intent = "competition"
COMPLIANCE: Intent = "compliance"
PROFILE: Intent = "profile"
UNKNOWN: Intent = "unknown"


KIND_INTENTS: dict[str, Intent] = {
    "renewal_due": RETENTION,
    "subscription_expiring": RETENTION,
    "plan_expiry": RETENTION,
    "membership_expiring": RETENTION,
    "winback_eligible": RETENTION,
    "customer_lapsed_soft": RETENTION,
    "customer_lapsed_hard": RETENTION,
    "dormant_with_vera": RETENTION,
    "recall_due": REMINDER,
    "chronic_refill_due": REMINDER,
    "appointment_due": REMINDER,
    "appointment_tomorrow": REMINDER,
    "trial_followup": REMINDER,
    "wedding_package_followup": REMINDER,
    "festival_upcoming": SEASONAL,
    "ipl_match_today": SEASONAL,
    "holiday_campaign": SEASONAL,
    "category_seasonal": SEASONAL,
    "active_planning_intent": PLANNING,
    "campaign_planning": PLANNING,
    "expansion_planning": PLANNING,
    "research_digest": INSIGHT,
    "trend_update": INSIGHT,
    "cde_opportunity": INSIGHT,
    "regulation_change": COMPLIANCE,
    "supply_alert": COMPLIANCE,
    "perf_dip": PERFORMANCE,
    "seasonal_perf_dip": PERFORMANCE,
    "perf_spike": PERFORMANCE,
    "milestone_reached": PERFORMANCE,
    "review_theme_emerged": REPUTATION,
    "competitor_opened": COMPETITION,
    "gbp_unverified": PROFILE,
}


KEYWORD_INTENTS: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    (COMPLIANCE, ("regulation", "compliance", "recall", "alert", "batch", "deadline", "authority")),
    (REMINDER, ("reminder", "recall", "refill", "appointment", "booking", "slot", "due")),
    (RETENTION, ("renewal", "subscription", "expiry", "expired", "winback", "lapsed", "dormant", "churn")),
    (SEASONAL, ("festival", "holiday", "season", "weather", "heatwave", "monsoon", "match", "event")),
    (PLANNING, ("planning", "campaign", "launch", "program", "package", "expansion", "intent")),
    (PERFORMANCE, ("performance", "dip", "spike", "views", "calls", "ctr", "leads", "milestone")),
    (REPUTATION, ("review", "rating", "theme", "complaint", "feedback")),
    (COMPETITION, ("competitor", "nearby", "opened", "rival")),
    (PROFILE, ("gbp", "google", "profile", "verified", "verification", "listing")),
    (INSIGHT, ("digest", "research", "trend", "news", "webinar", "cde", "source")),
)


def trigger_intent(trigger: dict[str, Any] | None, merchant: dict[str, Any] | None = None, category: dict[str, Any] | None = None) -> Intent:
    trigger = trigger or {}
    merchant = merchant or {}
    category = category or {}

    kind = normalize_text(str(trigger.get("kind") or "")).replace("-", "_").replace(" ", "_")
    if kind in KIND_INTENTS:
        return KIND_INTENTS[kind]

    payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
    tags = trigger.get("tags") or payload.get("tags") or []
    tag_text = " ".join(map(str, tags)) if isinstance(tags, list) else str(tags)
    payload_keys = " ".join(map(str, payload.keys()))
    payload_values = " ".join(str(v) for v in payload.values() if isinstance(v, (str, int, float, bool)))
    signals = " ".join(map(str, merchant.get("signals") or []))
    category_slug = str(merchant.get("category_slug") or category.get("slug") or "")
    text = normalize_text(" ".join([kind, tag_text, payload_keys, payload_values, signals, category_slug]))

    if str(trigger.get("scope") or "") == "customer" or trigger.get("customer_id"):
        if any(word in text for word in ("appointment", "recall", "refill", "trial", "visit", "lapsed", "slot", "due")):
            return REMINDER
        return RETENTION

    for intent, keywords in KEYWORD_INTENTS:
        if any(keyword in text for keyword in keywords):
            return intent

    urgency = int(trigger.get("urgency") or 0)
    if urgency >= 4 and any(payload.get(key) is not None for key in ("deadline_iso", "affected_batches", "molecule", "authority")):
        return COMPLIANCE
    if safe_get(merchant, "subscription", "days_remaining", default=None) is not None and urgency >= 3:
        return RETENTION
    if merchant.get("conversation_history") and urgency >= 3:
        return PLANNING
    if category.get("seasonal_beats") and urgency <= 3:
        return SEASONAL
    if category.get("digest") or category.get("trend_signals"):
        return INSIGHT
    return UNKNOWN


def intent_tier(intent: Intent) -> str:
    if intent in {COMPLIANCE, REMINDER, PROFILE}:
        return "Critical"
    if intent in {RETENTION, PERFORMANCE, REPUTATION, COMPETITION, PLANNING}:
        return "Operational"
    if intent == SEASONAL:
        return "Growth"
    return "Informational"


def intent_group(intent: Intent) -> str:
    if intent in {RETENTION, REMINDER}:
        return "retention"
    if intent in {COMPLIANCE, PROFILE}:
        return "compliance"
    if intent in {INSIGHT, SEASONAL}:
        return "informational"
    return "operational"
