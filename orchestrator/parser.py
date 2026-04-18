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


# Telegram bot token pattern: 10-12 digits : 30-60 alphanum chars
_TOKEN_RE = re.compile(r"\d{5,12}:[\w_-]{30,60}")

# Matches any natural variation of "create a secretary for X":
# crea/créale/haz/hazle/configura/añade/agrega un secretario/bot/asistente para/a/de X
_CREATE_PATTERN = re.compile(
    r"(?:crea(?:le)?|haz(?:le)?|configura|a[ñn]ade|agrega|registra|pon(?:le)?)\s+"
    r"(?:(?:un|el|al?)\s+)?(?:secretario|bot|asistente)\s+"
    r"(?:para\s+|a\s+|de\s+|al?\s+)?(?P<name>\w+)",
    re.IGNORECASE,
)

# Matches: "destruye/elimina/borra/quita secretario de X"
_DESTROY_PATTERN = re.compile(
    r"(?:destruye|elimina|borra|quita|desactiva)\s+(?:(?:al?\s+)?secretario\s+(?:de\s+)?)?(?P<name>\w+)",
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


def parse_command(
    text: str,
) -> (
    CreateSecretaryCommand
    | DestroySecretaryCommand
    | SendMessageCommand
    | ListSecretariesCommand
    | None
):
    """Parse natural language owner command. Returns a command dataclass or None."""
    if m := _LIST_PATTERN.search(text):
        return ListSecretariesCommand()

    if m := _CREATE_PATTERN.search(text):
        token_m = _TOKEN_RE.search(text)
        # Extract chatid: last standalone number of 5-15 digits not part of token
        text_no_token = _TOKEN_RE.sub("", text)
        chatid_m = re.search(r"(?<!\d)(\d{5,15})(?!\d)", text_no_token)

        token = token_m.group(0) if token_m else ""
        chat_id = chatid_m.group(1) if chatid_m else ""

        if not token or not chat_id:
            raise ValueError(
                "Para crear un secretario necesito el token del bot y el chat_id.\n"
                "Ejemplo: crea un secretario para María, token 123456:ABC... chatid 987654321"
            )
        return CreateSecretaryCommand(
            name=m.group("name"),
            telegram_token=token,
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
