import re

_DESTRUCTIVE_PATTERNS = (
    r"\brm\b",
    r"\brmdir\b",
    r"\bunlink\b",
    r"\bshred\b",
    r"\bwipefs\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bkill\b",
    r"\bpkill\b",
    r"\bkillall\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\bpasswd\b",
    r"\buserdel\b",
    r"\bgroupdel\b",
    r"DROP\s+TABLE",
    r"DROP\s+DATABASE",
    r"DELETE\s+FROM",
    r"\bTRUNCATE\b",
)

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _DESTRUCTIVE_PATTERNS]


def is_destructive(tool_name: str, args: dict) -> bool:
    """Return True if the tool call looks destructive and needs confirmation."""
    command = ""
    if tool_name in ("bash", "ssh_exec"):
        command = args.get("command", "")
    if not command:
        return False
    return any(pat.search(command) for pat in _COMPILED)
