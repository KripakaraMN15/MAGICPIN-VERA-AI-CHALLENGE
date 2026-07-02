from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional


LANG_PHRASES = {
    "en": {
        "greeting": "Hi",
        "ack": "Thanks",
        "cta_open": "Want me to",
        "cta_yes_stop": "Reply YES/STOP",
        "cta_confirm_cancel": "Reply CONFIRM/CANCEL",
        "closing": "Let me know if you want a draft.",
    },
    "hi": {
        "greeting": "Namaste",
        "ack": "Dhanyavaad",
        "cta_open": "Kya main",
        "cta_yes_stop": "YES/STOP me bataiye",
        "cta_confirm_cancel": "CONFIRM/CANCEL me bataiye",
        "closing": "Agar chaho toh main draft bana sakta hoon.",
    },
    "hi-en mix": {
        "greeting": "Hi",
        "ack": "Thanks",
        "cta_open": "Kya main",
        "cta_yes_stop": "Reply YES/STOP",
        "cta_confirm_cancel": "Reply CONFIRM/CANCEL",
        "closing": "Agar chaho toh main draft bana sakta hoon.",
    },
    "kn-en mix": {
        "greeting": "Hi",
        "ack": "Thanks",
        "cta_open": "Naan",
        "cta_yes_stop": "YES/STOP heLudaa",
        "cta_confirm_cancel": "CONFIRM/CANCEL heLudaa",
        "closing": "Beekagi irabeku, draft ready maadthene.",
    },
    "ta-en mix": {
        "greeting": "Hi",
        "ack": "Thanks",
        "cta_open": "Naan",
        "cta_yes_stop": "YES/STOP sollunga",
        "cta_confirm_cancel": "CONFIRM/CANCEL sollunga",
        "closing": "Venumna draft ready panni kudukiren.",
    },
    "te-en mix": {
        "greeting": "Hi",
        "ack": "Thanks",
        "cta_open": "Nenu",
        "cta_yes_stop": "YES/STOP cheppandi",
        "cta_confirm_cancel": "CONFIRM/CANCEL cheppandi",
        "closing": "Aavalsina draft ready chestanu.",
    },
    "mr": {
        "greeting": "Hi",
        "ack": "Thanks",
        "cta_open": "Main",
        "cta_yes_stop": "YES/STOP सांगा",
        "cta_confirm_cancel": "CONFIRM/CANCEL सांगा",
        "closing": "Hruvaya tar draft ready karu shakta.",
    },
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_get(d: Any, *path: str, default: Any = None) -> Any:
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def first_nonempty(*vals: Optional[str]) -> Optional[str]:
    for v in vals:
        if v is None:
            continue
        v2 = str(v).strip()
        if v2:
            return v2
    return None


_WS_SPACE = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    return _WS_SPACE.sub(" ", (s or "").strip().lower())


def clamp_str(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def has_any(text: str, needles: list[str]) -> bool:
    t = normalize_text(text)
    return any(n in t for n in needles)


_HINDI_CHARS = re.compile(r"[\u0900-\u097F]")
_HINDI_WORDS = {"hai", "hain", "nahi", "ka", "ki", "ke", "mein", "se", "ko", "ho", "kya", "yeh", "ap", "aap", "kar", "sakta", "sakti", "sakte", "mera", "meri", "mere", "hum", "aapka", "aapki", "aapke", "karo", "karoge", "karenge", "karti", "karta", "karte", "baat", "acha", "accha", "thik", "theek", "chahiye", "deta", "deti", "dete", "de", "do", "diya", "diye", "dijiye", "kijiye", "saman", "samajh", "suno", "sun", "bolo", "bol", "raha", "rahi", "rahe", "teek"}


def detect_language(text: Optional[str]) -> Optional[str]:
    """Detect if text contains Hindi (Devanagari or common Hindi words). Returns 'hi-en mix' or None."""
    if not text:
        return None
    if _HINDI_CHARS.search(text):
        return "hi-en mix"
    words = set(re.sub(r"[^a-zA-Z]+", " ", text.lower()).split())
    hindi_word_matches = words & _HINDI_WORDS
    if len(hindi_word_matches) >= 2:
        return "hi-en mix"
    return None


AUTO_REPLY_PATTERNS = [
    "thank you for contacting",
    "thanks for contacting",
    "our team will respond shortly",
    "we will get back to you",
    "this is an automated",
    "i am an automated",
    "we have received your message",
]


OPTOUT_PATTERNS = [
    "stop",
    "unsubscribe",
    "don't message",
    "do not message",
    "spam",
    "useless",
    "not interested",
]


COMMIT_PATTERNS = [
    "ok lets do it",
    "ok let's do it",
    "let's do it",
    "lets do it",
    "go ahead",
    "yes do it",
    "what's next",
    "whats next",
    "proceed",
    "start it",
]


def classify_reply(message: str) -> str:
    """
    Returns one of: auto_reply, opt_out, commit, other
    """
    if has_any(message, AUTO_REPLY_PATTERNS):
        return "auto_reply"
    if has_any(message, OPTOUT_PATTERNS):
        return "opt_out"
    if has_any(message, COMMIT_PATTERNS):
        return "commit"
    return "other"


def pick_language(languages: list[str] | None, customer_language_pref: str | None = None) -> str:
    """
    Normalize into one of: "en", "hi", "hi-en mix", "te-en mix", "kn-en mix", "ta-en mix", "mr"
    Default: "en"
    """
    pref = (customer_language_pref or "").strip().lower()
    if pref:
        return pref
    langs = [str(x).lower() for x in (languages or [])]
    if "hi" in langs and "en" in langs:
        return "hi-en mix"
    if "hi" in langs:
        return "hi"
    if "en" in langs:
        return "en"
    return langs[0] if langs else "en"


def apply_language(text: str, lang: str | None, *, fallback: str = "en") -> str:
    if not text:
        return ""
    lang_key = (lang or fallback).strip().lower()
    phrases = LANG_PHRASES.get(lang_key, LANG_PHRASES[fallback])
    if lang_key == fallback:
        return text
    text = text.replace("Want me to", phrases["cta_open"])
    text = text.replace("Reply YES/STOP", phrases["cta_yes_stop"])
    text = text.replace("Reply CONFIRM/CANCEL", phrases["cta_confirm_cancel"])
    text = text.replace("Let me know if you want a draft.", phrases["closing"])
    return text


def apply_category_voice(text: str, voice: dict[str, Any] | None) -> str:
    if not text or not isinstance(voice, dict):
        return text

    vocab_allowed = [str(x).strip().lower() for x in (voice.get("vocab_allowed") or []) if str(x).strip()]
    taboo = [str(x).strip().lower() for x in (voice.get("taboos") or voice.get("vocab_taboo") or voice.get("taboo") or []) if str(x).strip()]
    if not vocab_allowed and not taboo:
        return text

    result = text
    for word in taboo:
        result = re.sub(re.escape(word), "", result, flags=re.IGNORECASE)
    result = re.sub(r"\s+", " ", result).strip()

    replacements: dict[str, str] = {}
    if "check-up" in vocab_allowed:
        replacements["checkup"] = "check-up"

    for old, new in replacements.items():
        result = re.sub(re.escape(old), new, result, flags=re.IGNORECASE)
    return result if result else text


def salutation_for_category(category_slug: str, owner_first_name: str | None, merchant_name: str | None) -> str:
    slug = (category_slug or "").strip().lower()
    first = (owner_first_name or "").strip()
    if slug == "dentists":
        if first:
            if first.lower().startswith("dr"):
                return first
            return f"Dr. {first}"
        return first_nonempty(merchant_name, "Doctor") or "Doctor"
    # other categories: owner first name is best if present
    return first_nonempty(first, merchant_name, "Hi") or "Hi"
