import re


_ALIAS_MAP = {
    "星环": "transwarp",
    "星环科技": "transwarp",
    "星环公司": "transwarp",
    "transwarp": "transwarp",
}

_CN_SUFFIXES = ("有限公司", "集团", "股份", "科技", "公司")
_EN_SUFFIX_RE = re.compile(
    r"\b(inc|inc\.|corp|corp\.|corporation|co|co\.|ltd|ltd\.|limited|company|group)\b",
    flags=re.IGNORECASE,
)


def normalize_entity(value: str) -> str:
    s = (value or "").strip().lower()
    if not s:
        return ""

    # remove all spaces for better cache key stability
    s = re.sub(r"\s+", "", s)

    # strip common chinese suffixes
    for suf in _CN_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
            break

    # strip common english corporate suffixes
    s = _EN_SUFFIX_RE.sub("", s).strip()
    s = re.sub(r"[\s\-_]+", "", s)

    return _ALIAS_MAP.get(s, s)

