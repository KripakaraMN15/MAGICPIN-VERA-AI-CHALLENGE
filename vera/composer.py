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
    UNKNOWN,
    trigger_intent,
)
from .policy import CandidateSignal
from .utils import (
    apply_category_voice,
    apply_language,
    clamp_str,
    first_nonempty,
    pick_language,
    safe_get,
    salutation_for_category,
)


@dataclass(frozen=True)
class Composed:
    body: str
    cta: str
    send_as: str
    suppression_key: str
    rationale: str
    template_name: str
    template_params: list[str]


def _fmt_pct(x: Any) -> str:
    try:
        v = float(x)
        if -1.0 <= v <= 1.0:
            v = v * 100.0
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.0f}%"
    except Exception:
        return str(x)


def _pick_active_offer_title(merchant: dict[str, Any]) -> Optional[str]:
    offers = merchant.get("offers") or []
    for o in offers:
        if (o or {}).get("status") == "active":
            t = (o or {}).get("title")
            if t:
                return str(t)
    return None


def _top_digest_item(category: dict[str, Any], item_id: str | None) -> Optional[dict[str, Any]]:
    digest = category.get("digest") or []
    if item_id:
        for it in digest:
            if (it or {}).get("id") == item_id:
                return it
    return digest[0] if digest else None


def _build_context(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any] | None) -> dict[str, Any]:
    category_slug = str(first_nonempty(merchant.get("category_slug"), category.get("slug"), "unknown"))
    merchant_name = str(safe_get(merchant, "identity", "name", default="there"))
    owner_first = safe_get(merchant, "identity", "owner_first_name", default=None)
    locality = safe_get(merchant, "identity", "locality", default=None)
    city = safe_get(merchant, "identity", "city", default=None)
    languages = safe_get(merchant, "identity", "languages", default=[]) or []

    trig_kind = str(trigger.get("kind") or "unknown")
    trig_scope = str(trigger.get("scope") or "merchant")
    suppression_key = str(trigger.get("suppression_key") or f"{trig_kind}:{merchant.get('merchant_id', merchant_name)}")
    send_as = "merchant_on_behalf" if customer is not None else "vera"

    customer_name = safe_get(customer or {}, "identity", "name", default=None)
    customer_lang = safe_get(customer or {}, "identity", "language_pref", default=None)
    lang = pick_language(languages, customer_language_pref=customer_lang)
    salutation = salutation_for_category(category_slug, owner_first, merchant_name)

    return {
        "category": category,
        "merchant": merchant,
        "trigger": trigger,
        "customer": customer,
        "category_slug": category_slug,
        "merchant_name": merchant_name,
        "owner_first": owner_first,
        "locality": locality,
        "city": city,
        "languages": languages,
        "trig_kind": trig_kind,
        "trig_scope": trig_scope,
        "semantic_intent": trigger_intent(trigger, merchant, category),
        "suppression_key": suppression_key,
        "send_as": send_as,
        "customer_name": customer_name,
        "customer_lang": customer_lang,
        "lang": lang,
        "salutation": salutation,
        "views": safe_get(merchant, "performance", "views", default=None),
        "calls": safe_get(merchant, "performance", "calls", default=None),
        "ctr": safe_get(merchant, "performance", "ctr", default=None),
        "delta_views_7d": safe_get(merchant, "performance", "delta_7d", "views_pct", default=None),
        "delta_calls_7d": safe_get(merchant, "performance", "delta_7d", "calls_pct", default=None),
        "active_offer": _pick_active_offer_title(merchant),
        "category_voice": safe_get(category, "voice", default={}) or {},
        "peer_stats": safe_get(category, "peer_stats", default={}) or {},
        "trend_signals": safe_get(category, "trend_signals", default=[]) or [],
        "seasonal_beats": safe_get(category, "seasonal_beats", default=[]) or [],
        "signals": safe_get(merchant, "signals", default=[]) or [],
        "customer_aggregate": safe_get(merchant, "customer_aggregate", default={}) or {},
        "review_themes": safe_get(merchant, "review_themes", default=[]) or [],
        "conversation_history": safe_get(merchant, "conversation_history", default=[]) or [],
        "voice": safe_get(category, "voice", default={}) or {},
    }


def _build_composed(body: str, cta: str, send_as: str, suppression_key: str, rationale: str, template_name: str, template_params: list[str]) -> Composed:
    return Composed(
        body=body,
        cta=cta,
        send_as=send_as,
        suppression_key=suppression_key,
        rationale=rationale,
        template_name=template_name,
        template_params=template_params,
    )


def _apply_localization_and_voice(text: str, ctx: dict[str, Any]) -> str:
    lang = ctx.get("lang")
    voice = ctx.get("voice") or {}
    text = apply_language(text, lang)
    text = apply_category_voice(text, voice)
    return text


def _append_context_signal(parts: list[str], ctx: dict[str, Any], *, signal_text: str) -> None:
    if signal_text:
        parts.append(signal_text)


def _payload_label(ctx: dict[str, Any]) -> str:
    trigger = ctx["trigger"]
    payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
    for key in (
        "title",
        "campaign",
        "intent_topic",
        "program",
        "festival",
        "season",
        "match",
        "metric",
        "theme",
        "molecule",
        "service_due",
        "event_name",
    ):
        value = payload.get(key)
        if value:
            return str(value).replace("_", " ")
    return str(trigger.get("kind") or "this update").replace("_", " ")


def _first_review_theme(ctx: dict[str, Any]) -> str | None:
    themes = ctx.get("review_themes") or []
    if not themes:
        return None
    first = themes[0]
    if isinstance(first, dict):
        theme = first.get("theme")
        occ = first.get("occurrences_30d")
        if theme and occ:
            return f"{theme} showed up {occ}x in reviews"
        if theme:
            return str(theme).replace("_", " ")
    return str(first)


def _conversation_reuse(ctx: dict[str, Any]) -> str | None:
    history = ctx.get("conversation_history") or []
    for turn in reversed(history[-4:]):
        if not isinstance(turn, dict):
            continue
        body = str(turn.get("body") or "").strip()
        engagement = str(turn.get("engagement") or "")
        if body and ("intent" in engagement or turn.get("from") == "merchant"):
            return clamp_str(body, 120)
    return None


def _merchant_proof_parts(ctx: dict[str, Any], limit: int = 2) -> list[str]:
    proof: list[str] = []
    category_slug = str(ctx.get("category_slug") or "")
    if ctx.get("active_offer"):
        proof.append(f"your active offer is {ctx['active_offer']}")
    aggregate = ctx.get("customer_aggregate") or {}
    aggregate_labels = {
        "repeat_customer_pct": "repeat customers are at",
        "retention_6mo_pct": "6-month retention is",
        "retention_3mo_pct": "3-month retention is",
        "lapsed_180d_plus": "lapsed customer pool is",
        "chronic_rx_count": "chronic Rx customer count is",
        "delivery_orders_30d": "30d delivery orders are",
        "trial_to_paid_pct": "trial-to-paid conversion is",
        "total_active_members": "active member base is",
    }
    preferred_keys = ("chronic_rx_count", "repeat_customer_pct") if category_slug == "pharmacies" else (
        ("delivery_orders_30d", "repeat_customer_pct") if category_slug == "restaurants" else (
            ("trial_to_paid_pct", "total_active_members") if category_slug == "gyms" else tuple(aggregate_labels)
        )
    )
    for key in preferred_keys:
        if aggregate.get(key) is not None:
            proof.append(f"{aggregate_labels.get(key, key.replace('_', ' '))} {aggregate[key]}")
            break
    views = ctx.get("views")
    calls = ctx.get("calls")
    ctr = ctx.get("ctr")
    if views is not None and calls is not None:
        text = f"last 30d shows {views} views and {calls} calls"
        if ctr is not None:
            text += f", CTR {ctr}"
        proof.append(text)
    review = _first_review_theme(ctx)
    if review:
        proof.append(f"reviews mention {review}")
    peer_ctr = safe_get(ctx.get("peer_stats") or {}, "avg_ctr", default=None)
    if peer_ctr is not None:
        proof.append(f"peer CTR benchmark is {peer_ctr}")
    if ctx.get("signals"):
        proof.append(str(ctx["signals"][0]).replace("_", " "))
    return proof[:limit]


def _append_merchant_proof(parts: list[str], ctx: dict[str, Any], limit: int = 2) -> None:
    proof = _merchant_proof_parts(ctx, limit=limit)
    if proof:
        parts.append("For your store: " + "; ".join(proof) + ".")


def _handle_research_digest(ctx: dict[str, Any]) -> Composed:
    category = ctx["category"]
    merchant = ctx["merchant"]
    trigger = ctx["trigger"]
    salutation = ctx["salutation"]
    merchant_name = ctx["merchant_name"]
    locality = ctx["locality"]
    city = ctx["city"]
    suppression_key = ctx["suppression_key"]
    send_as = ctx["send_as"]

    top_item_id = safe_get(trigger, "payload", "top_item_id", default=None) or safe_get(trigger, "payload", "digest_item_id", default=None)
    item = _top_digest_item(category, top_item_id)
    title = safe_get(item or {}, "title", default=None) or safe_get(trigger, "payload", "title", default=None)
    if not title and safe_get(trigger, "payload", "molecule", default=None):
        molecule = safe_get(trigger, "payload", "molecule")
        manufacturer = safe_get(trigger, "payload", "manufacturer", default=None)
        title = f"{molecule} supply alert" + (f" from {manufacturer}" if manufacturer else "")
    title = title or ctx["trig_kind"].replace("_", " ")
    trial_n = safe_get(item or {}, "trial_n", default=None)
    deadline_iso = safe_get(item or {}, "deadline_iso", default=None) or safe_get(trigger, "payload", "deadline_iso", default=None)
    summary = safe_get(item or {}, "summary", default=None)
    actionable = safe_get(item or {}, "actionable", default=None)
    source = safe_get(item or {}, "source", default=None) or safe_get(trigger, "payload", "source", default=None)

    deadline_label = ""
    if deadline_iso:
        deadline_label = f". Deadline: {deadline_iso}"
    parts = [f"{salutation}, compliance update: {clamp_str(str(title), 140)}{deadline_label}"]
    if source and ctx["trig_kind"] == "supply_alert":
        parts.append(f"Source: {clamp_str(str(source), 100)}.")
    if summary and ctx["trig_kind"] != "supply_alert":
        parts.append(clamp_str(str(summary), 220))
    if actionable:
        parts.append(clamp_str(f"Suggested next step: {actionable}", 180))

    if ctx["trig_kind"] in ("regulation_change", "supply_alert"):
        molecule = safe_get(trigger, "payload", "molecule", default=None)
        manufacturer = safe_get(trigger, "payload", "manufacturer", default=None)
        batches = safe_get(trigger, "payload", "affected_batches", default=[]) or []
        if molecule:
            med_line = f"Medicine to check: {molecule}"
            if manufacturer:
                med_line += f" ({manufacturer})"
            if batches:
                med_line += "; batches " + ", ".join(map(str, batches[:3]))
            parts.append(med_line + ".")
        if safe_get(ctx["peer_stats"], "avg_ctr", default=None) is not None:
            parts.append(f"Peers in your category are already adjusting to this change.")
        _append_merchant_proof(parts, ctx)
        if ctx["trig_kind"] == "supply_alert":
            parts.append("Want me to draft a stock-check note and customer notice using only these details? Reply YES/STOP.")
        else:
            parts.append("I can draft a customer notice and a staff checklist. Reply YES/STOP.")
        return _build_composed(
            _apply_localization_and_voice(" ".join(parts), ctx),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "High-urgency compliance/alert trigger; cites provided source/payload facts and offers a grounded stock-check/customer notice draft.",
            "vera_compliance_alert_v1",
            [str(salutation), clamp_str(str(title), 120), clamp_str(str(actionable or "Want a draft you can use?"), 120)],
        )
    if ctx["trig_kind"] == "cde_opportunity":
        parts.append("Want the 2-line registration message to forward? Reply YES/STOP.")
        return _build_composed(
            _apply_localization_and_voice(" ".join(parts), ctx),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "CDE opportunity trigger; keeps it peer-toned and asks for a simple yes/no to receive a forwardable draft.",
            "vera_cde_v1",
            [str(salutation), clamp_str(str(title), 120), clamp_str(str(actionable or "Want a draft you can use?"), 120)],
        )
    if safe_get(ctx["trend_signals"], default=None) or safe_get(ctx["peer_stats"], default=None):
        parts.append("A useful angle here is the current peer adoption trend in your category.")
    parts.append("Want me to pull the key points and draft a shareable post for you?")
    return _build_composed(
        _apply_localization_and_voice(" ".join(parts), ctx),
        "open_ended",
        send_as,
        suppression_key,
        "Digest/seasonal trigger; grounded summary + offer to externalize effort into a draft, inviting reply.",
        "vera_research_digest_v1",
        [str(salutation), clamp_str(str(title), 120), clamp_str(str(actionable or "Want a draft you can use?"), 120)],
    )


def _handle_perf(ctx: dict[str, Any]) -> Composed:
    merchant = ctx["merchant"]
    trigger = ctx["trigger"]
    salutation = ctx["salutation"]
    merchant_name = ctx["merchant_name"]
    suppression_key = ctx["suppression_key"]
    send_as = ctx["send_as"]
    views = ctx["views"]
    calls = ctx["calls"]
    ctr = ctx["ctr"]
    delta_views_7d = ctx["delta_views_7d"]
    delta_calls_7d = ctx["delta_calls_7d"]
    active_offer = ctx["active_offer"]
    trig_kind = ctx["trig_kind"]

    parts: list[str] = []

    if trig_kind in ("perf_dip", "seasonal_perf_dip"):
        metric = safe_get(trigger, "payload", "metric", default="performance")
        delta = safe_get(trigger, "payload", "delta_pct", default=delta_calls_7d or delta_views_7d)
        window = safe_get(trigger, "payload", "window", default="7d")
        parts = [f"{salutation}, {metric} is down {_fmt_pct(delta)} this {window} at {merchant_name}."]
        # Add complementary metric that may be steady
        if metric == "views" and calls is not None and delta_calls_7d is not None and delta_calls_7d >= 0:
            parts.append(f"Calls remain steady at {calls} while views dipped — interested visitors are still reaching out.")
        elif metric == "calls" and views is not None:
            parts.append(f"Even with fewer calls, your listing still pulled {views} views — the audience is there.")
        elif views is not None and calls is not None:
            parts.append(f"Last 30d: {views} views, {calls} calls — the numbers show a correction may help.")
        if trig_kind == "seasonal_perf_dip":
            season_note = safe_get(trigger, "payload", "season_note", default=None)
            if season_note:
                label = season_note.replace("_", " ").replace("apr jun", "Apr-Jun")
                parts.append(f"This aligns with the expected {label} pattern — a refreshed post can help recover visibility.")
        peer_ctr = safe_get(ctx["peer_stats"], "avg_ctr", default=None)
        if peer_ctr is not None and ctr is not None:
            gap = float(peer_ctr) - float(ctr)
            gap_str = f"{gap:.4f}" if abs(gap) < 0.01 else f"{gap:.3f}"
            parts.append(f"Your CTR is {gap_str} below peer median — a listing refresh can help close the gap.")
        if active_offer:
            parts.append(f"You have {active_offer} active — running that front-and-centre can help.")
        parts.append("I can draft a refreshed listing description or campaign to help recover visibility. Reply YES/STOP.")
        return _build_composed(
            _apply_localization_and_voice(" ".join(parts), ctx),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "Performance dip trigger; includes real deltas and current performance, then offers a concrete artifact with a binary CTA.",
            "vera_perf_nudge_v1",
            [str(salutation), clamp_str(str(trig_kind.replace("_", " ")), 60), clamp_str(str(active_offer or merchant_name), 80)],
        )

    if trig_kind == "perf_spike":
        metric = safe_get(trigger, "payload", "metric", default="performance")
        delta = safe_get(trigger, "payload", "delta_pct", default=delta_views_7d)
        window = safe_get(trigger, "payload", "window", default="7d")
        driver = safe_get(trigger, "payload", "likely_driver", default=None)
        parts.append(f"{salutation}, {metric} is up {_fmt_pct(delta)} at {merchant_name} this {window}.")
        if driver:
            driver_clean = driver.replace("_", " ")
            parts.append(f"Looks like the {driver_clean} is driving it.")
            if views is not None and calls is not None:
                parts.append(f"Last month: {views} views and {calls} calls — your existing content is pulling attention, and a follow-up post could extend this window.")
        else:
            if views is not None and calls is not None and delta_views_7d is not None:
                parts.append(f"Last month you had {views} views and {calls} calls, and the 7d trend is positive — good moment to post again.")
        if safe_get(ctx["review_themes"], default=None):
            top = ctx["review_themes"][0]
            parts.append(f"Your reviews mention {top['theme'].replace('_', ' ')} ({top['occurrences_30d']}×) — that angle is already resonating with visitors.")
        if driver:
            parts.append(f"Want me to draft a follow-up post building on the {driver.replace('_', ' ')}?")
        else:
            parts.append("Want me to draft a post to keep the momentum going?")
        return _build_composed(
            _apply_localization_and_voice(" ".join(parts), ctx),
            "open_ended",
            send_as,
            suppression_key,
            "Performance spike trigger; acknowledges the lift and proposes a timely next step without fabricating details.",
            "vera_spike_followup_v1",
            [str(salutation), clamp_str(str(trig_kind.replace("_", " ")), 60), clamp_str(str(active_offer or merchant_name), 80)],
        )

    if trig_kind == "milestone_reached":
        metric = safe_get(trigger, "payload", "metric", default="milestone")
        value_now = safe_get(trigger, "payload", "value_now", default=None)
        milestone_value = safe_get(trigger, "payload", "milestone_value", default=None)
        parts = [f"{salutation}, milestone watch for {merchant_name}."]
        if value_now is not None and milestone_value is not None:
            parts.append(f"You're at {value_now} {metric} — {milestone_value} is close.")
        peer_ctr = safe_get(ctx["peer_stats"], "avg_ctr", default=None)
        if peer_ctr is not None and ctr is not None:
            parts.append(f"Similar {ctx['category_slug']} who cross this milestone see a measurable lift in discovery.")
        if safe_get(ctx["review_themes"], default=None):
            parts.append("Your review momentum makes this an easy ask — happy customers are already signaling.")
        parts.append("Want a 2-line review ask draft to cross it this week? Reply YES/STOP.")
        return _build_composed(
            _apply_localization_and_voice(" ".join(parts), ctx),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "Milestone trigger; uses social proof (peer benchmark) + review momentum to make the ask compelling.",
            "vera_milestone_v1",
            [str(salutation), clamp_str(str(trig_kind.replace("_", " ")), 60), clamp_str(str(active_offer or merchant_name), 80)],
        )

    if trig_kind == "review_theme_emerged":
        theme = safe_get(trigger, "payload", "theme", default=None)
        occ = safe_get(trigger, "payload", "occurrences_30d", default=None)
        quote = safe_get(trigger, "payload", "common_quote", default=None)
        parts = [f"{salutation}, recent reviews mention {theme.replace('_', ' ')} for {merchant_name} ({occ}× this month)."]
        if quote:
            parts.append(f'Customers are saying: "{clamp_str(str(quote), 90)}"')
        if views is not None:
            parts.append(f"You got {views} views this month — a short status update can set expectations before customers visit. Reply YES/STOP.")
        return _build_composed(
            _apply_localization_and_voice(" ".join(parts), ctx),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "Review-theme trigger; grounds on occurrences and quote, adds merchant proof, then offers two concrete artifacts with a single YES/STOP CTA.",
            "vera_reviews_v1",
            [str(salutation), clamp_str(str(trig_kind.replace("_", " ")), 60), clamp_str(str(active_offer or merchant_name), 80)],
        )

    comp = safe_get(trigger, "payload", "competitor_name", default="a nearby competitor")
    dist = safe_get(trigger, "payload", "distance_km", default=None)
    their_offer = safe_get(trigger, "payload", "their_offer", default=None)
    dist_str = f" {dist}km away" if dist is not None else ""
    offer_str = f", leading with {their_offer}" if their_offer else ""
    parts = [f"{salutation}, {comp} opened{dist_str}{offer_str}."]
    cust_agg = ctx.get("customer_aggregate") or {}
    total_unique = cust_agg.get("total_unique_ytd") or cust_agg.get("total_active_members")
    pos_reviews = [r for r in (ctx.get("review_themes") or []) if r.get("sentiment") == "pos"]
    advantages = []
    if total_unique:
        label = 'patients' if 'total_unique_ytd' in cust_agg else 'members'
        advantages.append(f"{total_unique} existing {label}")
    if pos_reviews:
        theme = pos_reviews[0]['theme'].replace('_', ' ')
        count = pos_reviews[0]['occurrences_30d']
        advantages.append(f"{count} recent reviews praising your {theme}")
    if advantages:
        parts.append(f"Your {', '.join(advantages)} are advantages no new listing can match.")
    if active_offer and not total_unique and not pos_reviews:
        parts.append(f"Your {active_offer} is already active — lead with that.")
    parts.append("I can draft a short post reminding your patients why they chose you. Reply YES/STOP.")
    return _build_composed(
        _apply_localization_and_voice(" ".join(parts), ctx),
        "binary_yes_stop",
        send_as,
        suppression_key,
        "Competitor trigger; references competitor name/distance/offer if provided and proposes a grounded positioning response.",
        "vera_competitor_v1",
        [str(salutation), clamp_str(str(trig_kind.replace("_", " ")), 60), clamp_str(str(active_offer or merchant_name), 80)],
    )


def _handle_customer_outreach(ctx: dict[str, Any]) -> Composed:
    trigger = ctx["trigger"]
    merchant_name = ctx["merchant_name"]
    customer_name = ctx["customer_name"] or "there"
    suppression_key = ctx["suppression_key"]
    send_as = ctx["send_as"]
    active_offer = ctx["active_offer"]
    trig_kind = ctx["trig_kind"]

    m_short = first_nonempty(merchant_name, "your clinic") or "your clinic"
    parts: list[str] = []
    parts.append(f"Hi {customer_name}, {m_short} here.")

    if trig_kind == "recall_due":
        last_service_date = safe_get(trigger, "payload", "last_service_date", default=None)
        due_date = safe_get(trigger, "payload", "due_date", default=None)
        slots = safe_get(trigger, "payload", "available_slots", default=[]) or []
        if last_service_date and due_date:
            parts.append(f"It's been since {last_service_date} — your recall is due around {due_date}.")
        if slots:
            labels = [s.get("label") for s in slots[:2] if isinstance(s, dict) and s.get("label")]
            if labels:
                parts.append("2 slots available: " + " or ".join(labels) + ".")
        if active_offer:
            parts.append(f"{active_offer}.")
        if slots:
            parts.append("Reply 1 for the first slot, 2 for the second, or share a time that works.")
            return _build_composed(
                _apply_localization_and_voice(" ".join(parts), ctx),
                "multi_choice_slot",
                send_as,
                suppression_key,
                "Customer recall trigger; uses provided last/due dates and slots, includes a concrete offer if available, and uses a low-friction slot CTA.",
                "merchant_recall_reminder_v1",
                [str(customer_name), str(m_short), clamp_str(str(due_date or "recall due"), 60), clamp_str(" / ".join([s.get("label", "") for s in slots[:2]]), 80), clamp_str(str(active_offer or ""), 80)],
            )
        parts.append("What time works for you this week?")
        return _build_composed(
            _apply_localization_and_voice(" ".join(parts), ctx),
            "open_ended",
            send_as,
            suppression_key,
            "Customer recall trigger; uses provided last/due dates and slots, includes a concrete offer if available, and uses a low-friction slot CTA.",
            "merchant_recall_reminder_v1",
            [str(customer_name), str(m_short), clamp_str(str(due_date or "recall due"), 60), clamp_str(" / ".join([s.get("label", "") for s in slots[:2]]), 80), clamp_str(str(active_offer or ""), 80)],
        )

    if trig_kind == "chronic_refill_due":
        molecules = safe_get(trigger, "payload", "molecule_list", default=[]) or []
        runs_out = safe_get(trigger, "payload", "stock_runs_out_iso", default=None)
        if molecules:
            parts.append("Your medicines: " + ", ".join(map(str, molecules[:4])) + ".")
        if runs_out:
            parts.append(f"Expected to run out by {runs_out.split('T')[0]}.")
        parts.append("Reply CONFIRM to dispatch, or CANCEL if there’s any dosage change.")
        return _build_composed(
            _apply_localization_and_voice(" ".join(parts), ctx),
            "binary_confirm_cancel",
            send_as,
            suppression_key,
            "Chronic refill trigger; lists molecules + run-out date from payload and ends with a clear CONFIRM/CANCEL CTA.",
            "merchant_refill_reminder_v1",
            [str(customer_name), str(m_short), clamp_str(", ".join(map(str, molecules[:4])), 80), clamp_str(str(runs_out or ""), 60)],
        )

    if trig_kind == "customer_lapsed_hard":
        days = safe_get(trigger, "payload", "days_since_last_visit", default=None)
        prev_focus = safe_get(trigger, "payload", "previous_focus", default=None)
        if days:
            parts.append(f"It’s been about {days} days since your last visit.")
        if prev_focus:
            parts.append(f"If you're still aiming for {prev_focus}, we can help you restart gently.")
        parts.append("Want us to hold a trial slot for you? Reply YES/STOP.")
        return _build_composed(
            _apply_localization_and_voice(" ".join(parts), ctx),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "Lapsed customer trigger; acknowledges lapse without guilt and offers a low-commitment YES/STOP to hold a slot.",
            "merchant_winback_v1",
            [str(customer_name), str(m_short), clamp_str(str(days or ""), 20)],
        )

    if trig_kind == "wedding_package_followup":
        wedding_date = safe_get(trigger, "payload", "wedding_date", default=None)
        days_to_wedding = safe_get(trigger, "payload", "days_to_wedding", default=None)
        next_step = safe_get(trigger, "payload", "next_step_window_open", default=None)
        if wedding_date:
            parts.append(f"Your wedding is on {wedding_date}.")
        if days_to_wedding is not None:
            parts.append(f"That leaves about {days_to_wedding} days to plan.")
        if next_step:
            parts.append(f"The next step window is {next_step}.")
        parts.append("I can help you turn this into a simple prep plan or a customer-facing offer.")
        return _build_composed(
            _apply_localization_and_voice(" ".join(parts), ctx),
            "open_ended",
            send_as,
            suppression_key,
            "Wedding follow-up trigger; uses the supplied wedding window and offers a concrete planning next step.",
            "merchant_customer_nudge_v1",
            [str(customer_name), str(m_short)],
        )

    parts.append("Quick check — want me to suggest the next best slot?")
    return _build_composed(
        _apply_localization_and_voice(" ".join(parts), ctx),
        "open_ended",
        send_as,
        suppression_key,
        "Customer-scoped trigger; simple check-in CTA without inventing facts.",
        "merchant_customer_nudge_v1",
        [str(customer_name), str(m_short)],
    )


def _handle_merchant_contextual(ctx: dict[str, Any]) -> Composed:
    merchant_name = ctx["merchant_name"]
    salutation = ctx["salutation"]
    suppression_key = ctx["suppression_key"]
    send_as = ctx["send_as"]
    trig_kind = ctx["trig_kind"]
    active_offer = ctx["active_offer"]
    signals = ctx["signals"]
    customer_aggregate = ctx["customer_aggregate"]
    peer_stats = ctx["peer_stats"]

    if trig_kind == "renewal_due":
        days_remaining = safe_get(ctx["trigger"], "payload", "days_remaining", default=None)
        plan = safe_get(ctx["trigger"], "payload", "plan", default=None)
        renewal_amount = safe_get(ctx["trigger"], "payload", "renewal_amount", default=None)
        parts = [f"{salutation}, {merchant_name} has {days_remaining} days left on the {plan} plan."]
        if safe_get(ctx["signals"], default=None):
            parts.append("A renewal reminder is especially useful here because your current signals point to a timely follow-up.")
        if renewal_amount is not None:
            parts.append(f"Renewal is {renewal_amount}.")
        if active_offer:
            parts.append(f"Your current offer is {active_offer}.")
        parts.append("Want me to draft a short renewal note for your team? Reply YES/STOP.")
        return _build_composed(
            " ".join(parts),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "Renewal trigger; cites the renewal window and cost and offers a low-friction next step.",
            "vera_renewal_v1",
            [str(salutation), clamp_str(str(merchant_name), 80), clamp_str(str(days_remaining or ""), 20)],
        )

    if trig_kind == "festival_upcoming":
        festival = safe_get(ctx["trigger"], "payload", "festival", default=None)
        days_until = safe_get(ctx["trigger"], "payload", "days_until", default=None)
        date_value = safe_get(ctx["trigger"], "payload", "date", default=None)
        parts = [f"{salutation}, {festival} is {days_until} days away on {date_value}."]
        if safe_get(ctx["seasonal_beats"], default=None):
            parts.append("This period is typically active for nearby merchants in your category.")
        if active_offer:
            parts.append(f"Your current offer is {active_offer}.")
        parts.append("Want a simple festival-ready offer line for this week?")
        return _build_composed(
            " ".join(parts),
            "open_ended",
            send_as,
            suppression_key,
            "Festival trigger; uses the supplied festival timing and offers an easy next step without inventing new offers.",
            "vera_festival_v1",
            [str(salutation), clamp_str(str(festival or "festival"), 40), clamp_str(str(date_value or ""), 30)],
        )

    if trig_kind == "curious_ask_due":
        parts = [f"{salutation},"]
        agg = ctx.get("customer_aggregate") or {}
        lapsed = agg.get("lapsed_180d_plus") or agg.get("lapsed_90d_plus")
        retention = agg.get("retention_6mo_pct") or agg.get("retention_3mo_pct")
        lost_something = False
        if lapsed is not None:
            period = "6+" if agg.get("lapsed_180d_plus") is not None else "3+"
            parts.append(f"{lapsed} of your regulars haven't visited in {period} months — that's revenue walking out the door.")
            lost_something = True
        elif retention is not None:
            pct = float(retention) * 100 if -1 <= float(retention) <= 1 else float(retention)
            label = "6-month" if agg.get("retention_6mo_pct") is not None else "3-month"
            parts.append(f"Your {label} retention is {pct:.0f}% — peers in your category typically aim above 50%.")
            lost_something = True
        if not lost_something:
            _append_merchant_proof(parts, ctx)
        if active_offer:
            parts.append(f"You can use {active_offer} as the hook.")
        parts.append("Reply YES to see their names + what they last booked — 5 min to pull.")
        return _build_composed(
            " ".join(parts),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "Curious-ask trigger; uses loss aversion (lapsed customers) + effort externalization (5-min pull) to drive engagement.",
            "vera_curious_ask_v1",
            [str(salutation), clamp_str(str(active_offer or merchant_name), 80)],
        )

    if trig_kind == "ipl_match_today":
        match = safe_get(ctx["trigger"], "payload", "match", default=None)
        venue = safe_get(ctx["trigger"], "payload", "venue", default=None)
        city = safe_get(ctx["trigger"], "payload", "city", default=None)
        match_time = safe_get(ctx["trigger"], "payload", "match_time_iso", default=None)
        parts = [f"{salutation}, {match} is on today in {city}."]
        if venue:
            vicinity = safe_get(ctx["merchant"], "identity", "locality", default=None)
            parts.append(f"The {venue} is nearby — match-day foot traffic could mean extra visitors searching for options like yours.")
        if active_offer:
            parts.append(f"Your {active_offer} can give match-day visitors a reason to pick you.")
        parts.append("Want a 1-line post to run with it today? Reply YES/STOP.")
        return _build_composed(
            " ".join(parts),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "IPL trigger; uses the supplied match details to make the outreach timely and specific.",
            "vera_ipl_v1",
            [str(salutation), clamp_str(str(match or "match"), 40), clamp_str(str(city or ""), 40)],
        )

    if trig_kind == "active_planning_intent":
        intent_topic = safe_get(ctx["trigger"], "payload", "intent_topic", default=None)
        merchant_last_message = safe_get(ctx["trigger"], "payload", "merchant_last_message", default=None)
        topic_label = str(intent_topic or "this plan").replace("_", " ")
        parts = [f"{salutation}, I can help you shape the plan around {topic_label} for {merchant_name}."]
        if merchant_last_message:
            parts.append(f"You mentioned: {merchant_last_message}.")
        if active_offer:
            parts.append(f"Your current {active_offer} could slot right in.")
        ctx_views, ctx_calls = ctx.get("views"), ctx.get("calls")
        if ctx_views and ctx_calls:
            parts.append(f"You're seeing {ctx_views} views and {ctx_calls} calls this month — the audience is there.")
        parts.append("Want me to draft an offer or rollout outline? Reply YES/STOP.")
        return _build_composed(
            " ".join(parts),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "Active planning trigger; uses the stated intent and prior merchant note to propose a next step.",
            "vera_planning_v1",
            [str(salutation), clamp_str(str(intent_topic or "plan"), 60)],
        )

    if trig_kind == "winback_eligible":
        days_since_expiry = safe_get(ctx["trigger"], "payload", "days_since_expiry", default=None)
        perf_dip_pct = safe_get(ctx["trigger"], "payload", "perf_dip_pct", default=None)
        lapsed_customers = safe_get(ctx["trigger"], "payload", "lapsed_customers_added_since_expiry", default=None)
        parts = [f"{salutation}, {merchant_name} has lapsed customers still reachable."]
        if days_since_expiry is not None:
            parts.append(f"It's been {days_since_expiry} days since expiry — re-engagement windows shrink fast.")
        if perf_dip_pct is not None:
            parts.append(f"Performance dipped {_fmt_pct(perf_dip_pct)}.")
        if lapsed_customers is not None:
            parts.append(f"{lapsed_customers} are still warm — each one you reactivate recovers lost ground.")
        parts.append("Want a 2-line winback draft? Reply YES/STOP.")
        return _build_composed(
            " ".join(parts),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "Winback trigger; uses loss aversion (shrinking window) + concrete lapsed-customer count to create urgency.",
            "vera_winback_v1",
            [str(salutation), clamp_str(str(merchant_name), 80)],
        )

    if trig_kind == "dormant_with_vera":
        days_since_last_merchant_message = safe_get(ctx["trigger"], "payload", "days_since_last_merchant_message", default=None)
        last_topic = safe_get(ctx["trigger"], "payload", "last_topic", default=None)
        views = ctx.get("views")
        calls = ctx.get("calls")
        agg = ctx.get("customer_aggregate") or {}
        parts = [f"{salutation}, {days_since_last_merchant_message} days since your last update."]
        if views is not None and calls is not None:
            parts.append(f"Your listing still gets {views} views monthly — but only {calls} calls, so visitors aren't converting.")
        lapsed = agg.get("lapsed_180d_plus") or agg.get("lapsed_90d_plus")
        if lapsed:
            parts.append(f"In fact, {lapsed} regulars haven't been back — a post could bring some of them in.")
        if last_topic:
            parts.append(f"We last talked about {last_topic.replace('_', ' ')}.")
        parts.append("Want 1 post idea to get things moving?")
        return _build_composed(
            " ".join(parts),
            "open_ended",
            send_as,
            suppression_key,
            "Dormancy trigger; uses the last-contact lag and listing traffic to suggest a light re-engagement with a single next step.",
            "vera_dormancy_v1",
            [str(salutation), clamp_str(str(merchant_name), 80)],
        )

    if trig_kind == "gbp_unverified":
        verified = safe_get(ctx["trigger"], "payload", "verified", default=None)
        path = safe_get(ctx["trigger"], "payload", "verification_path", default=None)
        uplift = safe_get(ctx["trigger"], "payload", "estimated_uplift_pct", default=None)
        parts = [f"{salutation}, your GBP listing is still unverified."]
        if path:
            parts.append(f"The path is {path}.")
        if uplift is not None:
            parts.append(f"Estimated uplift is {_fmt_pct(uplift)}.")
        parts.append("Want me to draft a quick verification reminder? Reply YES/STOP.")
        return _build_composed(
            " ".join(parts),
            "binary_yes_stop",
            send_as,
            suppression_key,
            "GBP verification trigger; uses the supplied verification state and lift estimate for a direct nudge.",
            "vera_gbp_v1",
            [str(salutation), clamp_str(str(merchant_name), 80)],
        )

    return _build_composed(
        f"{salutation}, quick ping for {merchant_name}: I can help draft a sharp message for '{trig_kind}'. Want me to?",
        "open_ended",
        send_as,
        suppression_key,
        "Fallback composition for unknown trigger kind; avoids hallucination and asks a low-effort question.",
        "vera_generic_v1",
        [str(salutation), clamp_str(merchant_name, 60), clamp_str(trig_kind, 60)],
    )


def _handle_intent_retention(ctx: dict[str, Any]) -> Composed:
    trigger = ctx["trigger"]
    payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
    parts = [f"{ctx['salutation']}, quick retention signal for {ctx['merchant_name']}."]
    days = first_nonempty(payload.get("days_remaining"), payload.get("days_since_expiry"), safe_get(ctx["merchant"], "subscription", "days_remaining", default=None))
    plan = first_nonempty(payload.get("plan"), safe_get(ctx["merchant"], "subscription", "plan", default=None))
    if days and plan:
        parts.append(f"Plan context: {plan}, {days} days in the current renewal/expiry window.")
    elif days:
        parts.append(f"Timing context: {days} days in the current retention window.")
    if payload.get("lapsed_customers_added_since_expiry") is not None:
        parts.append(f"{payload['lapsed_customers_added_since_expiry']} lapsed customers are available to re-engage.")
    _append_merchant_proof(parts, ctx)
    prior = _conversation_reuse(ctx)
    if prior:
        parts.append(f"Earlier context: {prior}.")
    parts.append("Want me to draft the shortest next-step message for this window? Reply YES/STOP.")
    return _build_composed(
        _apply_localization_and_voice(" ".join(parts), ctx),
        "binary_yes_stop",
        ctx["send_as"],
        ctx["suppression_key"],
        "Semantic retention intent; uses renewal/lapse timing, merchant proof, and prior conversation when available.",
        "vera_retention_intent_v1",
        [str(ctx["salutation"]), clamp_str(ctx["merchant_name"], 80), clamp_str(str(days or _payload_label(ctx)), 60)],
    )


def _handle_intent_reminder(ctx: dict[str, Any]) -> Composed:
    trigger = ctx["trigger"]
    payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
    if ctx.get("customer"):
        return _handle_customer_outreach(ctx)

    parts = [f"{ctx['salutation']}, reminder opportunity for {ctx['merchant_name']}: {_payload_label(ctx)}."]
    for key in ("due_date", "appointment_date", "stock_runs_out_iso", "last_service_date", "trial_date"):
        if payload.get(key):
            parts.append(f"{key.replace('_', ' ')}: {payload[key]}.")
            break
    slots = payload.get("available_slots") or payload.get("next_session_options") or []
    if isinstance(slots, list) and slots:
        labels = [s.get("label") for s in slots[:2] if isinstance(s, dict) and s.get("label")]
        if labels:
            parts.append("Available slots: " + " or ".join(labels) + ".")
    _append_merchant_proof(parts, ctx)
    parts.append("Want me to draft the customer-safe reminder text from only these details? Reply YES/STOP.")
    return _build_composed(
        _apply_localization_and_voice(" ".join(parts), ctx),
        "binary_yes_stop",
        "vera",
        ctx["suppression_key"],
        "Semantic reminder intent without customer context; stays merchant-facing and avoids inferring customer details.",
        "vera_reminder_intent_v1",
        [str(ctx["salutation"]), clamp_str(ctx["merchant_name"], 80), clamp_str(_payload_label(ctx), 60)],
    )


def _handle_intent_seasonal(ctx: dict[str, Any]) -> Composed:
    trigger = ctx["trigger"]
    payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
    label = _payload_label(ctx)
    date_value = first_nonempty(payload.get("date"), payload.get("match_time_iso"), payload.get("event_date"))
    parts = [f"{ctx['salutation']}, {label} is coming up — timely for {ctx['merchant_name']}."]
    if date_value:
        parts.append(f"Date: {date_value}.")
    if payload.get("venue") or payload.get("city"):
        parts.append("Location: " + ", ".join([str(x) for x in (payload.get("venue"), payload.get("city")) if x]) + ".")
    trends = payload.get("trends")
    if isinstance(trends, list) and trends:
        parts.append("Trend signal: " + ", ".join(map(str, trends[:3])).replace("_", " ") + ".")
    elif ctx.get("trend_signals"):
        trend = ctx["trend_signals"][0]
        if isinstance(trend, dict):
            parts.append(f"Category search trend: {trend.get('query')} up {_fmt_pct(trend.get('delta_yoy'))} YoY — customers are actively looking.")
    _append_merchant_proof(parts, ctx)
    parts.append("Want a one-line campaign draft tied to this timing? Reply YES/STOP.")
    return _build_composed(
        _apply_localization_and_voice(" ".join(parts), ctx),
        "binary_yes_stop",
        ctx["send_as"],
        ctx["suppression_key"],
        "Semantic seasonal intent; grounds on event timing and trend signals with a clear why-now hook instead of a generic opener.",
        "vera_seasonal_intent_v1",
        [str(ctx["salutation"]), clamp_str(label, 60), clamp_str(str(date_value or ""), 40)],
    )


def _handle_intent_planning(ctx: dict[str, Any]) -> Composed:
    trigger = ctx["trigger"]
    payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
    topic = first_nonempty(payload.get("intent_topic"), payload.get("campaign"), payload.get("program"), _payload_label(ctx))
    parts = [f"{ctx['salutation']}, I can turn {topic} into a concrete rollout for {ctx['merchant_name']}."]
    prior = first_nonempty(payload.get("merchant_last_message"), _conversation_reuse(ctx))
    if prior:
        parts.append(f"Earlier context: {clamp_str(str(prior), 140)}.")
    _append_merchant_proof(parts, ctx, limit=3)
    parts.append("Want me to draft the launch message plus the first operational step? Reply YES/STOP.")
    return _build_composed(
        _apply_localization_and_voice(" ".join(parts), ctx),
        "binary_yes_stop",
        ctx["send_as"],
        ctx["suppression_key"],
        "Semantic planning intent; reuses prior conversation and merchant evidence to avoid a generic planning prompt.",
        "vera_planning_intent_v1",
        [str(ctx["salutation"]), clamp_str(str(topic), 80), clamp_str(ctx["merchant_name"], 80)],
    )


def _handle_intent_insight(ctx: dict[str, Any]) -> Composed:
    trigger = ctx["trigger"]
    payload = trigger.get("payload") if isinstance(trigger.get("payload"), dict) else {}
    item_id = payload.get("top_item_id") or payload.get("digest_item_id") or payload.get("alert_id")
    item = _top_digest_item(ctx["category"], item_id)
    title = first_nonempty(payload.get("title"), safe_get(item or {}, "title", default=None), _payload_label(ctx))
    parts = [f"{ctx['salutation']}, quick insight for {ctx['merchant_name']}: {clamp_str(str(title), 150)}."]
    source = safe_get(item or {}, "source", default=None) or payload.get("source")
    if source:
        parts.append(f"Source: {source}.")
    actionable = safe_get(item or {}, "actionable", default=None) or payload.get("actionable")
    if actionable:
        parts.append(f"Suggested next step: {clamp_str(str(actionable), 140)}.")
    _append_merchant_proof(parts, ctx)
    parts.append("Want me to turn this into a merchant-ready post or customer note? Reply YES/STOP.")
    return _build_composed(
        _apply_localization_and_voice(" ".join(parts), ctx),
        "binary_yes_stop",
        ctx["send_as"],
        ctx["suppression_key"],
        "Semantic insight intent; cites supplied digest/source/actionable details and merchant evidence.",
        "vera_insight_intent_v1",
        [str(ctx["salutation"]), clamp_str(str(title), 100), clamp_str(str(actionable or ""), 80)],
    )


def _handle_intent_operational(ctx: dict[str, Any]) -> Composed:
    label = _payload_label(ctx)
    trig_kind = ctx["trig_kind"]
    parts = [f"{ctx['salutation']}, {label} for {ctx['merchant_name']}."]
    views = ctx.get("views")
    calls = ctx.get("calls")
    ctr = ctx.get("ctr")
    peer_ctr = safe_get(ctx.get("peer_stats") or {}, "avg_ctr", default=None)
    signals = ctx.get("signals") or []
    if views is not None and calls is not None:
        parts.append(f"Last 30d: {views} views and {calls} calls.")
    if peer_ctr is not None and ctr is not None and float(ctr) < float(peer_ctr):
        parts.append(f"Your CTR of {ctr} trails the peer median of {peer_ctr} — similar businesses nearby capture more from the same views.")
    elif signals:
        parts.append(f"Flagged: {signals[0].replace('_', ' ')}.")
    _append_merchant_proof(parts, ctx, limit=2)
    prior = _conversation_reuse(ctx)
    if prior:
        parts.append(f"Earlier: {prior}.")
    if trig_kind in ("milestone_reached", "perf_spike"):
        parts.append("Want me to draft a post while this window is open? Reply YES/STOP.")
    elif trig_kind in ("competitor_opened",):
        parts.append("Want a 1-line counter-positioning draft? Reply YES/STOP.")
    else:
        parts.append("Want me to convert this into 1 actionable step for this week? Reply YES/STOP.")
    return _build_composed(
        _apply_localization_and_voice(" ".join(parts), ctx),
        "binary_yes_stop",
        ctx["send_as"],
        ctx["suppression_key"],
        "Semantic operational fallback; uses available merchant evidence before falling back to a generic next step.",
        "vera_operational_intent_v1",
        [str(ctx["salutation"]), clamp_str(label, 80), clamp_str(ctx["merchant_name"], 80)],
    )


INTENT_HANDLERS = {
    RETENTION: _handle_intent_retention,
    REMINDER: _handle_intent_reminder,
    SEASONAL: _handle_intent_seasonal,
    PLANNING: _handle_intent_planning,
    INSIGHT: _handle_intent_insight,
    COMPLIANCE: _handle_intent_insight,
    PERFORMANCE: _handle_intent_operational,
    REPUTATION: _handle_intent_operational,
    COMPETITION: _handle_intent_operational,
    PROFILE: _handle_intent_operational,
    UNKNOWN: _handle_intent_operational,
}


HANDLERS = {
    "research_digest": _handle_research_digest,
    "regulation_change": _handle_research_digest,
    "cde_opportunity": _handle_research_digest,
    "supply_alert": _handle_research_digest,
    "category_seasonal": _handle_intent_seasonal,
    "perf_dip": _handle_perf,
    "seasonal_perf_dip": _handle_perf,
    "perf_spike": _handle_perf,
    "milestone_reached": _handle_perf,
    "review_theme_emerged": _handle_perf,
    "competitor_opened": _handle_perf,
    "recall_due": _handle_customer_outreach,
    "trial_followup": _handle_customer_outreach,
    "appointment_tomorrow": _handle_customer_outreach,
    "chronic_refill_due": _handle_customer_outreach,
    "customer_lapsed_soft": _handle_customer_outreach,
    "customer_lapsed_hard": _handle_customer_outreach,
    "wedding_package_followup": _handle_customer_outreach,
    "renewal_due": _handle_merchant_contextual,
    "festival_upcoming": _handle_merchant_contextual,
    "curious_ask_due": _handle_merchant_contextual,
    "ipl_match_today": _handle_merchant_contextual,
    "active_planning_intent": _handle_merchant_contextual,
    "winback_eligible": _handle_merchant_contextual,
    "dormant_with_vera": _handle_merchant_contextual,
    "gbp_unverified": _handle_merchant_contextual,
}


def compose(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any] | None) -> Composed:
    ctx = _build_context(category, merchant, trigger, customer)
    handler = HANDLERS.get(ctx["trig_kind"])
    if not handler:
        handler = INTENT_HANDLERS.get(ctx["semantic_intent"], _handle_intent_operational)
    return handler(ctx)


def build_candidate_signals(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any] | None) -> list[CandidateSignal]:
    ctx = _build_context(category, merchant, trigger, customer)
    handler = HANDLERS.get(ctx["trig_kind"]) or INTENT_HANDLERS.get(ctx["semantic_intent"], _handle_intent_operational)
    handler_name = handler.__name__
    return [
        CandidateSignal(
            merchant_id=str(merchant.get("merchant_id") or "unknown"),
            category=str(ctx["category_slug"]),
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            handler_name=handler_name,
            suppression_key=ctx["suppression_key"],
            conversation_scope="customer" if ctx["trig_scope"] == "customer" else "merchant",
            priority=0,
        )
    ]
