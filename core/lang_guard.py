from core.lang_detect import detect_lang, normalize_lang


def _language_name(lang: str) -> str:
    normalized = normalize_lang(lang, default="en")
    return {
        "zh": "Chinese",
        "en": "English",
        "ko": "Korean",
    }.get(normalized, "English")


def enforce_language(text: str, lang: str, llm=None) -> str:
    content = (text or "").strip()
    if not content:
        return content

    target_lang = normalize_lang(lang, default="en")
    detected_lang = detect_lang(content)
    if detected_lang == target_lang:
        return content

    if llm is not None:
        try:
            prompt = (
                f"Rewrite the following text into {_language_name(target_lang)}.\n"
                "Keep the meaning unchanged. Do not add extra content.\n\n"
                f"{content}\n"
            )
            rewritten = str(llm.complete(prompt)).strip()
            if rewritten and detect_lang(rewritten) == target_lang:
                return rewritten
        except Exception:  # noqa: BLE001
            pass

    return content
