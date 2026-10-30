"""Bounded streaming redaction for common PII formats."""

import re

from config import HOLDBACK, REDACTED

EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,32}"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,8}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,8}[A-Za-z0-9])?)?"
    r"\.[A-Za-z]{2,6}(?![A-Za-z0-9.-])"
)
SSN_PATTERN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,15}\d(?!\d)")
PII_PATTERNS = (EMAIL_PATTERN, SSN_PATTERN, CARD_PATTERN)


def redact_text(text: str) -> str:
    """Redact complete matches while preserving unmatched surrounding text."""
    matches = sorted(
        (match for pattern in PII_PATTERNS for match in pattern.finditer(text)),
        key=lambda match: match.start(),
    )
    if not matches:
        return text

    parts: list[str] = []
    cursor = 0
    for match in matches:
        if match.start() < cursor:
            continue
        parts.extend((text[cursor : match.start()], REDACTED))
        cursor = match.end()
    parts.append(text[cursor:])
    return "".join(parts)


class StreamRedactor:
    """Redact streaming text while retaining a fixed-size undecided suffix."""

    HOLDBACK = HOLDBACK

    def __init__(self) -> None:
        self.buffer = ""

    def feed(self, delta: str) -> str:
        """Add one text delta and return the prefix proven safe to emit."""
        self.buffer += delta
        commit_at = max(0, len(self.buffer) - self.HOLDBACK)
        if commit_at == 0:
            return ""

        for pattern in PII_PATTERNS:
            for match in pattern.finditer(self.buffer):
                if match.start() < commit_at < match.end():
                    commit_at = match.start()
                if match.end() == len(self.buffer) and match.start() < commit_at:
                    commit_at = match.start()

        committed = self.buffer[:commit_at]
        self.buffer = self.buffer[commit_at:]
        return redact_text(committed)

    def flush(self) -> str:
        """Redact and return the remaining suffix at end of stream."""
        remaining = redact_text(self.buffer)
        self.buffer = ""
        return remaining
