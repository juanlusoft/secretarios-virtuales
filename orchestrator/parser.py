import re
from dataclasses import dataclass


@dataclass
class CreateSecretaryCommand:
    name: str
    telegram_token: str
    telegram_chat_id: str


@dataclass
class DestroySecretaryCommand:
    name: str


@dataclass
class SendMessageCommand:
    name: str
    message: str


@dataclass
class ListSecretariesCommand:
    pass


# Matches: "crea [un] secretario para X ... TOKEN CHATID"
# TOKEN format: digits:alphanum (Telegram bot token)
# CHATID: sequence of digits (5-15 chars)
_CREATE_PATTERN = re.compile(
    r"crea\s+(?:un\s+)?secretario\s+(?:para\s+)?(?P<name>\w+)"
    r".*?"
    r"(?:token[:\s]+)?(?P<token>\d{5,12}:[\w_-]{30,60})"
    r".*?"
    r"(?:chat_?id[:\s]+)?(?P<chatid>\d{5,15})",
    re.IGNORECASE | re.DOTALL,
)

# Matches: "destruye/elimina/borra secretario de X"
_DESTROY_PATTERN = re.compile(
    r"(?:destruye|elimina|borra)\s+(?:(?:al?\s+)?secretario\s+(?:de\s+)?)?(?P<name>\w+)",
    re.IGNORECASE,
)

# Matches: "avisa/dile/manda a X que ..." or "mensaje para X: ..."
_SEND_PATTERN = re.compile(
    r"(?:avisa|d[ií]le|manda(?:le)?|mensaje\s+para)\s+(?:a\s+)?(?P<name>\w+)[^\w]*"
    r"(?:que\s+)?(?P<message>.+)",
    re.IGNORECASE,
)

# Matches: "lista/muestra secretarios"
_LIST_PATTERN = re.compile(
    r"(?:lista|muestra|ver|show)\s+(?:los\s+)?secretarios?",
    re.IGNORECASE,
)


def parse_command(text: str):
    """Parse natural language owner command. Returns a command dataclass or None."""
    if m := _LIST_PATTERN.search(text):
        return ListSecretariesCommand()

    if m := _CREATE_PATTERN.search(text):
        chat_id = m.group("chatid") or ""
        if not chat_id:
            raise ValueError(
                "chat_id es obligatorio para crear un secretario. "
                "Incluye el chat_id numérico en tu mensaje."
            )
        return CreateSecretaryCommand(
            name=m.group("name"),
            telegram_token=m.group("token"),
            telegram_chat_id=chat_id,
        )

    if m := _DESTROY_PATTERN.search(text):
        return DestroySecretaryCommand(name=m.group("name"))

    if m := _SEND_PATTERN.search(text):
        return SendMessageCommand(
            name=m.group("name"),
            message=m.group("message").strip(),
        )

    return None
