#!/usr/bin/env python3
"""
Smoke test for the candidate bot without any LLM API key.

It:
- calls /healthz + /metadata
- pushes a minimal set of contexts from dataset seeds
- pushes 1-3 triggers
- calls /tick and prints returned actions
- calls /reply once to validate the shape
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as urlrequest


BOT_URL = os.environ.get("BOT_URL", "http://127.0.0.1:8080").rstrip("/")
DATASET_DIR = Path(__file__).parent / "dataset"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _req(method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
    url = f"{BOT_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urlrequest.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_seed(name: str) -> dict:
    with open(DATASET_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    # Avoid Windows console encoding crashes on ₹ etc.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

    print(f"Bot: {BOT_URL}")

    print("\nGET /v1/healthz")
    print(_req("GET", "/v1/healthz", None, timeout=5))

    print("\nGET /v1/metadata")
    print(_req("GET", "/v1/metadata", None, timeout=5))

    # Push categories (5)
    print("\nPushing category contexts…")
    for f in (DATASET_DIR / "categories").glob("*.json"):
        payload = json.load(open(f, "r", encoding="utf-8"))
        body = {"scope": "category", "context_id": payload["slug"], "version": 1, "payload": payload, "delivered_at": _now_iso()}
        resp = _req("POST", "/v1/context", body, timeout=10)
        print(f"  category/{payload['slug']}: {resp.get('accepted')} ({resp.get('reason','')})")

    # Push a few merchants + customers + triggers
    merchants = load_seed("merchants_seed.json")["merchants"]
    customers = load_seed("customers_seed.json")["customers"]
    triggers = load_seed("triggers_seed.json")["triggers"]

    print("\nPushing 3 merchants…")
    for m in merchants[:3]:
        body = {"scope": "merchant", "context_id": m["merchant_id"], "version": 1, "payload": m, "delivered_at": _now_iso()}
        resp = _req("POST", "/v1/context", body, timeout=10)
        print(f"  merchant/{m['merchant_id']}: {resp.get('accepted')}")

    print("\nPushing 3 customers…")
    for c in customers[:3]:
        body = {"scope": "customer", "context_id": c["customer_id"], "version": 1, "payload": c, "delivered_at": _now_iso()}
        resp = _req("POST", "/v1/context", body, timeout=10)
        print(f"  customer/{c['customer_id']}: {resp.get('accepted')}")

    print("\nPushing 3 triggers…")
    trig_ids: list[str] = []
    bump = int(time.time())
    for t in triggers[:3]:
        # Make suppression_key unique so repeated smoke tests still produce actions.
        t = dict(t)
        t["suppression_key"] = f"{t.get('suppression_key','')}:smoke:{bump}"
        trig_ids.append(t["id"])
        body = {"scope": "trigger", "context_id": t["id"], "version": bump, "payload": t, "delivered_at": _now_iso()}
        resp = _req("POST", "/v1/context", body, timeout=10)
        print(f"  trigger/{t['id']}: {resp.get('accepted')}")

    print("\nPOST /v1/tick")
    tick = _req("POST", "/v1/tick", {"now": _now_iso(), "available_triggers": trig_ids}, timeout=15)
    print(json.dumps(tick, indent=2, ensure_ascii=False)[:4000])

    actions = tick.get("actions") or []
    if not actions:
        print("\nNo actions returned (valid).")
        return

    a0 = actions[0]
    print("\nPOST /v1/reply (simulate merchant reply)")
    reply_body = {
        "conversation_id": a0["conversation_id"],
        "merchant_id": a0["merchant_id"],
        "customer_id": a0.get("customer_id"),
        "from_role": "merchant",
        "message": "Ok lets do it. Whats next?",
        "received_at": _now_iso(),
        "turn_number": 2,
    }
    rep = _req("POST", "/v1/reply", reply_body, timeout=15)
    print(rep)


if __name__ == "__main__":
    main()

