from __future__ import annotations

import re

# Defense-in-depth policy for agent-generated shell commands. Docker remains the
# primary isolation boundary; this layer prevents obviously dangerous requests.
BLOCKED_PATTERNS = (
    r"(^|\s)(curl|wget|nc|ncat|netcat)(\s|$)",
    r"(^|\s)(ssh|scp|sftp)(\s|$)",
    r"(^|\s)docker(\s|$)",
    r"(^|\s)(chmod|chown)\s",
    r"(^|\s)(rm|rmdir|del)\s+(-rf|/|\\)",
    r"(^|\s)git\s+(reset|clean|checkout\s+--)",
    r"(^|\s)(mkfs|dd)\s",
)

def validate_command(command: str) -> tuple[bool, str]:
    normalized = command.strip()
    if len(normalized) > 12000:
        return False, "Command exceeds the maximum allowed length."
    lowered = normalized.lower()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, lowered):
            return False, "Command blocked by CodeForge security policy."
    return True, ""
