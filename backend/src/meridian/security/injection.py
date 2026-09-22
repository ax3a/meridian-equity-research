"""Prompt-injection detection for retrieved (untrusted) content.

Detection is a signal, not the defence: the primary defence is structural — untrusted text is only ever
placed inside delimited evidence blocks in the user turn, after system-level rules that declare it data.
"""

from __future__ import annotations

import re

_PATTERNS: dict[str, re.Pattern[str]] = {
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|all|earlier|system)\b"
        r"[^.\n]{0,20}\b(instructions?|prompts?|rules|directions)\b", re.I),
    "role_hijack": re.compile(r"\b(you are now|act as|pretend to be|from now on,? you)\b", re.I),
    "system_prompt_probe": re.compile(r"\b(system prompt|developer message|hidden instructions|reveal your)\b", re.I),
    "fake_role_marker": re.compile(r"(^|\n)\s*(system|assistant|human|user)\s*:\s", re.I),
    "tag_breakout": re.compile(r"</?\s*(untrusted_evidence|trusted_context|system|instructions)\b", re.I),
    "new_instructions": re.compile(r"\b(new|updated|additional) (instructions|task|directive)s?\s*:", re.I),
    "tool_injection": re.compile(r'"(tool|function)(_name)?"\s*:\s*"', re.I),
    "rating_manipulation": re.compile(
        r"\b(rate|recommend|say|state|conclude)\b[^.\n]{0,30}\b(strong buy|buy rating|must buy|sell immediately)\b",
        re.I),
}

_TAG_RE = re.compile(r"<\s*/?\s*(untrusted_evidence|trusted_context|system|instructions)[^>]*>", re.I)


def scan(text: str) -> list[str]:
    """Return the names of injection patterns found in `text`."""
    return [name for name, pattern in _PATTERNS.items() if pattern.search(text)]


def neutralize(text: str) -> str:
    """Remove delimiter-like tags so untrusted text cannot close or forge an evidence block."""
    return _TAG_RE.sub("[tag removed]", text)
