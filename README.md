# magicpin Vera AI Challenge — Candidate Bot

This repository contains a **stateful HTTP bot** that implements the judging contract from `challenge-testing-brief.md`:

- `GET /v1/healthz`
- `GET /v1/metadata`
- `POST /v1/context`
- `POST /v1/tick`
- `POST /v1/reply`

The core composition is **deterministic**: same context inputs → same output.

## How to run

### Prerequisites

- Python 3.10+
- OpenAI API key (for the LLM judge; the bot itself runs without one)
- Install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

### Start the bot

```bash
uvicorn bot:app --host 0.0.0.0 --port 8080
```

### Run the judge simulator

Configure `.env` with your LLM provider settings, then:

```bash
# Full evaluation (all triggers)
python judge_simulator.py

# Phase 2 short (3 triggers, quick smoke test)
set TEST_SCENARIO=phase2_short
python judge_simulator.py

# Other scenarios: warmup, auto_reply_hell, intent_transition, hostile
```

Edit `judge_simulator.py` config at the top to set `BOT_URL` if needed.

### Run unit tests

```bash
python -m pytest tests/ -v
```

### Generate submission.jsonl

```bash
python -c "
from vera.composer import compose
# See gen_submission.py in the repo for the full script
"
```

## Constraints

This bot respects all challenge constraints:

| Constraint | How it's handled |
|---|---|
| **WhatsApp 24h session** | Tick actions include `template_name` and `template_params` ({{1}}/{{2}}/…); reply handler tracks conversation state within the session window. |
| **Single primary CTA** | Binary `binary_yes_stop` for action triggers; `open_ended` for info/curiosity triggers. Never multiple CTAs. |
| **URLs allowed** | Bot may include URLs when they add clear value per the spec; no artificial stripping. |
| **Specificity wins** | Messages anchor on verifiable facts: exact counts (views/calls/deltas), real dates, actual offer names. |
| **Voice match** | Peer/colleague tone per category: formal for dentists ("Dr. Meera"), casual for salons ("Hi Kavya"). Taboo words enforced per category voice. |
| **Hindi-English code-mix** | Language detection in `/v1/reply` handler (`bot.py:223`); detects Devanagari or common Hindi words and localizes subsequent replies. |
| **No fabrication** | All data sourced from pushed contexts only. No fake offers, citations, or competitor names. |
| **10 req/s rate limit** | Async FastAPI; responses <1s. |
| **30s per-call timeout** | Responses typically <500ms. |
| **500KB context payload** | Contexts stored in memory; no hard cap enforcement needed for test payload sizes. |
| **20 actions/tick** | Selection policy caps at 20 actions (`vera/policy.py`); scored and prioritized. |
| **No persistent state** | In-memory state only; acceptable for test-run duration. Reset on restart. |
| **Handles unknown triggers** | Unrecognized trigger kinds produce a safe no-op response via fallback handler. |
| **Idempotent context push** | Same version → 200 no-op; stale version (existing is higher) → 409. |

## Design

- **Context store**: `/v1/context` stores versioned contexts in memory, idempotent by `(scope, context_id, version)`.
- **Suppression**: per-trigger `suppression_key` is deduped with a TTL-like rule (in-memory for the test run).
- **Composer**: dispatches by `trigger.kind` and selects a small number of high-signal facts (numbers/offers/dates) without hallucinating.
- **Conversation handling**: `/v1/reply` detects auto-replies, opt-outs/hostility, and "commitment" intent transitions ("ok let's do it").
- **Language detection**: Per-turn detection via Devanagari chars + Hindi word heuristics; applies `apply_language()` to reply messages.

## Approach, Model, and Tradeoffs

### Approach
- **Deterministic rule-based composer**: No ML or randomness; uses hardcoded templates per trigger kind, grounded only on provided context fields.
- **Selective evidence prioritization**: Picks best signals (e.g., real deltas, offers, dates) over generic fluff; avoids dumping all facts.
- **Stateful suppression and conversation tracking**: Prevents duplicate sends; handles auto-replies and intent shifts.
- **Category/merchant fit**: Salutations and tone adapt to category (e.g., "Dr. Meera" for dentists); messages are concise, peer-toned.

### Model
- **Core logic**: `vera/composer.py` routes by `trigger.kind`, extracts grounded facts, applies templates.
- **No external APIs**: Pure Python, no hallucinations; URLs allowed when valuable.
- **Performance**: In-memory state; fast responses (<1s); handles 500KB context cap.

### Tradeoffs
- **Pros**: Deterministic, fast, low-resource, explainable (rationale in output), grounded, no API costs.
- **Cons**: Limited creativity (no generative AI); may miss nuanced triggers if not explicitly handled; in-memory state not persistent across restarts (acceptable for test).
- **Score ceiling**: Deterministic templates score ~38/50 with gpt-4o-mini judge. Higher scores (43+) likely require switching to an LLM-based composer.

## Deployment

Deploy this FastAPI server on Render/Fly/Railway/Azure/etc:

- Set the public base URL as `BOT_URL` in the judge config
- Procfile included for Heroku-style platforms
- Run the full simulator: `python judge_simulator.py`
- Submit the public bot URL
