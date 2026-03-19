import re


def normalize_lang(lang: str | None, default: str = "zh") -> str:
    value = (lang or "").strip().lower()
    if value.startswith("zh"):
        return "zh"
    if value.startswith("ko"):
        return "ko"
    if value.startswith("en"):
        return "en"
    return default


def detect_lang(text: str) -> str:
    if not text:
        return "zh"

    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"

    if re.search(r"[\uac00-\ud7a3]", text):
        return "ko"

    return "en"


def resolve_query_language(text: str, ui_lang: str | None, default: str = "zh") -> dict[str, object]:
    normalized_ui = normalize_lang(ui_lang, default=default)
    stripped = (text or "").strip()
    detected = detect_lang(stripped) if stripped else ""
    final_lang = normalize_lang(detected or normalized_ui or default, default=default)

    return {
        "lang_ui": normalized_ui,
        "lang_detected": detected or normalized_ui,
        "lang_final": final_lang,
        "suggest_switch": bool(detected and detected != normalized_ui),
    }
