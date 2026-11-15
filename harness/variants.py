"""Shared instruction change for the epistemics sprint's prompt arm."""
import os

PROMPT_SENTENCE = (
    "If a tool returns an empty, incomplete or unreadable result, say so plainly "
    "and do not fill in or estimate the missing values."
)


def instructions(original: str) -> str:
    if os.environ.get("ROI_VARIANT", "baseline") == "prompt":
        return original + "\n" + PROMPT_SENTENCE
    return original
