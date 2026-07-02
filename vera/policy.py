from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .intents import (
    COMPLIANCE,
    COMPETITION,
    INSIGHT,
    PERFORMANCE,
    PLANNING,
    PROFILE,
    REMINDER,
    REPUTATION,
    RETENTION,
    SEASONAL,
    intent_group,
    intent_tier,
    trigger_intent,
)
from .utils import normalize_text


@dataclass(frozen=True)
class CandidateSignal:
    """Represents one potential action that the selection layer may consider."""

    merchant_id: str
    category: Optional[str] = None
    merchant: Optional[dict[str, Any]] = None
    trigger: Optional[dict[str, Any]] = None
    customer: Optional[dict[str, Any]] = None
    handler_name: Optional[str] = None
    suppression_key: Optional[str] = None
    conversation_scope: str = "merchant"
    priority: int = 0
    score: Optional["PriorityScore"] = None


@dataclass(frozen=True)
class PriorityScore:
    """Simple additive scoring model for explainable ranking."""

    urgency: int = 0
    business_impact: int = 0
    merchant_readiness: int = 0
    customer_relevance: int = 0
    specificity: int = 0
    expected_value: int = 0
    peer_gap_bonus: int = 0
    merchant_signal_bonus: int = 0
    seasonality_bonus: int = 0
    review_theme_bonus: int = 0
    customer_readiness_bonus: int = 0
    suppression_penalty: int = 0
    repetition_penalty: int = 0
    total: int = 0
    rationale: tuple[str, ...] = ()

    @classmethod
    def from_parts(
        cls,
        urgency: int = 0,
        business_impact: int = 0,
        merchant_readiness: int = 0,
        customer_relevance: int = 0,
        specificity: int = 0,
        expected_value: int = 0,
        peer_gap_bonus: int = 0,
        merchant_signal_bonus: int = 0,
        seasonality_bonus: int = 0,
        review_theme_bonus: int = 0,
        customer_readiness_bonus: int = 0,
        suppression_penalty: int = 0,
        repetition_penalty: int = 0,
        rationale: tuple[str, ...] | list[str] | None = None,
    ) -> "PriorityScore":
        rationale_items = tuple(rationale or ())
        total = (
            urgency
            + business_impact
            + merchant_readiness
            + customer_relevance
            + specificity
            + expected_value
            + peer_gap_bonus
            + merchant_signal_bonus
            + seasonality_bonus
            + review_theme_bonus
            + customer_readiness_bonus
            - suppression_penalty
            - repetition_penalty
        )
        return cls(
            urgency=urgency,
            business_impact=business_impact,
            merchant_readiness=merchant_readiness,
            customer_relevance=customer_relevance,
            specificity=specificity,
            expected_value=expected_value,
            peer_gap_bonus=peer_gap_bonus,
            merchant_signal_bonus=merchant_signal_bonus,
            seasonality_bonus=seasonality_bonus,
            review_theme_bonus=review_theme_bonus,
            customer_readiness_bonus=customer_readiness_bonus,
            suppression_penalty=suppression_penalty,
            repetition_penalty=repetition_penalty,
            total=total,
            rationale=rationale_items,
        )


@dataclass
class SelectionPolicy:
    """Deterministic selection layer for tick actions."""

    min_score: int = 6
    max_actions: int = 20
    max_new_conversations_per_merchant: int = 1

    def choose(self, candidates: list[CandidateSignal], state: Any) -> list[CandidateSignal]:
        return [decision["candidate"] for decision in self.decide(candidates, state) if decision["decision"] == "SEND"]

    def decide(self, candidates: list[CandidateSignal], state: Any) -> list[dict[str, Any]]:
        if not candidates:
            return []

        scored: list[tuple[CandidateSignal, PriorityScore]] = []
        for candidate in candidates:
            score = self._score_candidate(candidate, state)
            scored.append((candidate, score))

        scored.sort(key=lambda item: self._rank_key(item[0], item[1]))

        decisions: list[dict[str, Any]] = []
        send_candidates: list[CandidateSignal] = []
        send_counts: dict[str, int] = {}

        for candidate, score in scored:
            if self._is_invalid(candidate):
                decisions.append(self._decision(candidate, score, "REJECT", "candidate is invalid or missing required context"))
                continue

            if self._is_suppressed(candidate, state):
                decisions.append(self._decision(candidate, score, "REJECT", "candidate is suppressed"))
                continue

            if self._has_conflict(candidate, send_candidates):
                if self._effective_priority(candidate) > self._effective_priority(self._conflicting_candidate(candidate, send_candidates)):
                    previous = self._conflicting_candidate(candidate, send_candidates)
                    for existing in decisions:
                        if existing["candidate"] is previous and existing["decision"] == "SEND":
                            existing["decision"] = "DEFER"
                            existing["reason"] = "replaced by a higher-priority conflicting candidate"
                            break
                    send_candidates.remove(previous)
                else:
                    decisions.append(self._decision(candidate, score, "DEFER", "conflicts with a higher-priority send for the same merchant"))
                    continue

            if score.total < self.min_score and not self._is_informational_only_viable(candidate, [item[0] for item in scored], state):
                decisions.append(self._decision(candidate, score, "DEFER", "below the current threshold but still potentially valuable"))
                continue

            merchant_id = str(candidate.merchant_id or "")
            current_budget = send_counts.get(merchant_id, 0)
            if merchant_id and current_budget >= self.max_new_conversations_per_merchant:
                decisions.append(self._decision(candidate, score, "DEFER", "merchant attention budget exhausted for this tick"))
                continue

            if merchant_id:
                send_counts[merchant_id] = current_budget + 1
            send_candidates.append(candidate)
            decisions.append(self._decision(candidate, score, "SEND", "meets priority and budget requirements"))

            if len(send_candidates) >= self.max_actions:
                break

        return decisions

    def _rank_key(self, candidate: CandidateSignal, score: PriorityScore) -> tuple[Any, ...]:
        return (
            self._tier_rank(candidate),
            -score.total,
            -self._effective_priority(candidate),
            candidate.merchant_id,
            str((candidate.trigger or {}).get("kind") or ""),
        )

    def _score_candidate(self, candidate: CandidateSignal, state: Any) -> PriorityScore:
        trigger = candidate.trigger or {}
        intent = trigger_intent(trigger, candidate.merchant, None)
        urgency = int(trigger.get("urgency") or 0)
        suppression_penalty = 0
        repetition_penalty = 0
        rationale: list[str] = []

        if candidate.suppression_key and self._is_suppressed(candidate, state):
            suppression_penalty = 2
            rationale.append("suppression penalty: candidate is already suppressed")

        if self._was_recently_similar(candidate, state):
            repetition_penalty = 3
            rationale.append("recent similarity penalty: a similar trigger was already sent")

        business_impact = self._business_impact(candidate, intent)
        merchant_readiness = self._merchant_readiness(candidate, intent)
        customer_relevance = 2 if candidate.customer is not None else (0 if trigger.get("customer_id") else 1)
        specificity = self._specificity(candidate)
        expected_value = self._expected_value(candidate)

        # Small deterministic bonuses that reward context-rich signals without introducing randomness.
        peer_gap_bonus = 1 if self._has_peer_gap(candidate) else 0
        merchant_signal_bonus = 2 if self._has_merchant_signal(candidate) else 0
        seasonality_bonus = 1 if self._has_seasonality_signal(candidate) else 0
        review_theme_bonus = 1 if self._has_review_theme(candidate) else 0
        customer_readiness_bonus = 1 if self._has_customer_readiness(candidate) else 0

        rationale.append(
            f"Urgency={urgency} because the trigger is time-sensitive. Business impact={business_impact} because the trigger affects revenue or visibility. Merchant readiness={merchant_readiness} because the merchant context suggests a useful next step. Customer relevance={customer_relevance} because the message is customer-scoped. Specificity={specificity} because the trigger is concrete. Expected value={expected_value} because the trigger is likely to produce a useful response. Peer gap bonus={peer_gap_bonus} because the merchant is underperforming relative to the category. Merchant signal bonus={merchant_signal_bonus} because merchant signals indicate a strong opportunity. Seasonality bonus={seasonality_bonus} because the trigger aligns with seasonal demand. Review theme bonus={review_theme_bonus} because the merchant has recurring review feedback. Customer readiness bonus={customer_readiness_bonus} because the customer context suggests a likely response."
        )
        return PriorityScore.from_parts(
            urgency=urgency,
            business_impact=business_impact,
            merchant_readiness=merchant_readiness,
            customer_relevance=customer_relevance,
            specificity=specificity,
            expected_value=expected_value,
            peer_gap_bonus=peer_gap_bonus,
            merchant_signal_bonus=merchant_signal_bonus,
            seasonality_bonus=seasonality_bonus,
            review_theme_bonus=review_theme_bonus,
            customer_readiness_bonus=customer_readiness_bonus,
            suppression_penalty=suppression_penalty,
            repetition_penalty=repetition_penalty,
            rationale=rationale,
        )

    def _decision(self, candidate: CandidateSignal, score: PriorityScore, decision: str, reason: str) -> dict[str, Any]:
        return {
            "candidate": candidate,
            "decision": decision,
            "trigger_kind": str((candidate.trigger or {}).get("kind") or ""),
            "merchant_id": str(candidate.merchant_id or ""),
            "score": score,
            "reason": reason,
        }

    def _is_invalid(self, candidate: CandidateSignal) -> bool:
        if not candidate.merchant_id:
            return True
        if not (candidate.trigger or {}).get("kind"):
            return True
        if (candidate.trigger or {}).get("customer_id") and candidate.customer is None:
            return True
        return False

    def _is_informational_only_viable(self, candidate: CandidateSignal, all_candidates: list[CandidateSignal], state: Any) -> bool:
        if self._tier_rank(candidate) != self._tier_rank_for_name("Informational"):
            return False
        if self._is_suppressed(candidate, state):
            return False
        for other in all_candidates:
            if other is candidate:
                continue
            if self._is_suppressed(other, state):
                continue
            other_score = self._score_candidate(other, state)
            if other_score.total >= self.min_score:
                return False
        return True

    def _is_suppressed(self, candidate: CandidateSignal, state: Any) -> bool:
        suppression_key = str((candidate.suppression_key or "") or "")
        if not suppression_key:
            return False
        if hasattr(state, "is_suppressed"):
            return bool(state.is_suppressed(suppression_key))
        if hasattr(state, "suppressed"):
            return bool(getattr(state, "suppressed", {}).get(suppression_key, 0) > 0)
        return False

    def _was_recently_similar(self, candidate: CandidateSignal, state: Any) -> bool:
        trigger = candidate.trigger or {}
        kind = str(trigger.get("kind") or "")
        merchant_id = str(candidate.merchant_id or "")
        if not merchant_id or not kind:
            return False

        if not hasattr(state, "conversations"):
            return False

        recent_texts = []
        for conversation in state.conversations.values():
            if conversation.merchant_id != merchant_id:
                continue
            if conversation.last_bot_body_norm:
                recent_texts.append(conversation.last_bot_body_norm)

        if not recent_texts:
            return False

        norm = normalize_text(kind)
        return any(norm in text for text in recent_texts) or any(kind.lower() in text for text in recent_texts)

    def _has_conflict(self, candidate: CandidateSignal, selected: list[CandidateSignal]) -> bool:
        if not selected:
            return False
        candidate_merchant = str(candidate.merchant_id or "")
        candidate_group = self._category_group(candidate)
        for existing in selected:
            existing_merchant = str(existing.merchant_id or "")
            if candidate_merchant != existing_merchant:
                continue
            if self._category_group(existing) != candidate_group:
                continue
            return True
        return False

    def _conflicting_candidate(self, candidate: CandidateSignal, selected: list[CandidateSignal]) -> CandidateSignal:
        candidate_merchant = str(candidate.merchant_id or "")
        candidate_group = self._category_group(candidate)
        for existing in selected:
            existing_merchant = str(existing.merchant_id or "")
            if candidate_merchant != existing_merchant:
                continue
            if self._category_group(existing) != candidate_group:
                continue
            return existing
        raise ValueError("No conflicting candidate found")

    def _effective_priority(self, candidate: CandidateSignal) -> int:
        trigger = candidate.trigger or {}
        urgency = int(trigger.get("urgency") or 0)
        tier_rank = self._tier_rank(candidate)
        return (100 - tier_rank) * 100 + urgency * 10 + self._expected_value(candidate) * 3

    def _expected_value(self, candidate: CandidateSignal) -> int:
        intent = trigger_intent(candidate.trigger, candidate.merchant, None)
        if intent in {COMPLIANCE, REMINDER, RETENTION, PROFILE}:
            return 3
        if intent in {PLANNING, PERFORMANCE, REPUTATION, COMPETITION, SEASONAL}:
            return 2
        return 1

    def _business_impact(self, candidate: CandidateSignal, intent: str) -> int:
        merchant = candidate.merchant or {}
        trigger = candidate.trigger or {}
        payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
        if intent in {COMPLIANCE, PROFILE}:
            return 3
        if intent in {RETENTION, REMINDER}:
            return 2
        if any(payload.get(key) is not None for key in ("renewal_amount", "estimated_uplift_pct", "perf_dip_pct", "lapsed_customers_added_since_expiry")):
            return 2
        if merchant.get("customer_aggregate") or safe_merchant_has_performance(merchant):
            return 2
        return 1

    def _merchant_readiness(self, candidate: CandidateSignal, intent: str) -> int:
        merchant = candidate.merchant or {}
        trigger = candidate.trigger or {}
        payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
        history = merchant.get("conversation_history") or []
        signals = merchant.get("signals") or []
        if intent == PLANNING or payload.get("merchant_last_message"):
            return 3
        if history or signals or merchant.get("offers"):
            return 2
        return 1

    def _specificity(self, candidate: CandidateSignal) -> int:
        merchant = candidate.merchant or {}
        trigger = candidate.trigger or {}
        payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
        concrete = 0
        concrete += sum(1 for value in payload.values() if isinstance(value, (int, float)) or (isinstance(value, str) and any(ch.isdigit() for ch in value)))
        concrete += 1 if merchant.get("offers") else 0
        concrete += 1 if safe_merchant_has_performance(merchant) else 0
        concrete += 1 if merchant.get("review_themes") else 0
        concrete += 1 if merchant.get("customer_aggregate") else 0
        return 2 if concrete >= 2 else 1

    def _has_peer_gap(self, candidate: CandidateSignal) -> bool:
        merchant = candidate.merchant or {}
        signals = merchant.get("signals") or []
        return any("ctr_below_peer" in str(x).lower() for x in signals)

    def _has_merchant_signal(self, candidate: CandidateSignal) -> bool:
        merchant = candidate.merchant or {}
        signals = merchant.get("signals") or []
        return bool(signals)

    def _has_seasonality_signal(self, candidate: CandidateSignal) -> bool:
        merchant = candidate.merchant or {}
        trigger = candidate.trigger or {}
        payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
        seasonality = merchant.get("seasonal_beats") or []
        return bool(seasonality or payload.get("season") or payload.get("festival") or payload.get("event_name"))

    def _has_review_theme(self, candidate: CandidateSignal) -> bool:
        merchant = candidate.merchant or {}
        themes = merchant.get("review_themes") or []
        return bool(themes)

    def _has_customer_readiness(self, candidate: CandidateSignal) -> bool:
        return candidate.customer is not None

    def _tier_rank(self, candidate: CandidateSignal) -> int:
        return self._tier_rank_for_name(self._priority_tier(candidate))

    def _tier_rank_for_name(self, tier: str) -> int:
        return {"Critical": 0, "Operational": 1, "Growth": 2, "Informational": 3}.get(tier, 3)

    def _priority_tier(self, candidate: CandidateSignal) -> str:
        return intent_tier(trigger_intent(candidate.trigger, candidate.merchant, None))

    def _category_group(self, candidate: CandidateSignal) -> str:
        return intent_group(trigger_intent(candidate.trigger, candidate.merchant, None))


def safe_merchant_has_performance(merchant: dict[str, Any]) -> bool:
    performance = merchant.get("performance") if isinstance(merchant, dict) else None
    if not isinstance(performance, dict):
        return False
    return any(performance.get(key) is not None for key in ("views", "calls", "ctr", "leads", "directions"))
