# Onboarding, Email Config & System Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guided onboarding flow on `/start`, a `/config_email` command with domain auto-detection, and an improved system prompt that reflects the bot's personality and real capabilities.

**Architecture:** ConversationHandlers (python-telegram-bot) are built as factory functions that close over the `SecretaryAgent` instance. Profile data (bot name, gender, user name, language, capabilities flags) is stored encrypted in the existing `credentials` table with `service_type='profile'`. No DB migration required.

**Tech Stack:** Python 3.11+, python-telegram-bot v20+, asyncpg, cryptography (Fernet), pytest, pytest-asyncio

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `secretary/handlers/_email_providers.py` | `KNOWN_PROVIDERS` dict — single source of truth |
| Create | `secretary/handlers/onboarding.py` | `build_onboarding_handler(agent)` → ConversationHandler |
| Create | `secretary/handlers/config_email.py` | `build_config_email_handler(agent)` → ConversationHandler |
| Modify | `secretary/handlers/text.py` | New SYSTEM_TEMPLATE + `profile` param in `handle_text` |
| Modify | `secretary/agent.py` | `_profile` attr, `_load_profile`, `_save_profile`, `_save_email_credentials`; register handlers in `run()` |
| Create | `tests/secretary/test_email_providers.py` | Tests for provider detection helper |
| Create | `tests/secretary/test_onboarding.py` | Tests for gender detection and onboarding states |
| Create | `tests/secretary/test_config_email.py` | Tests for config_email ConversationHandler states |
| Modify | `tests/secretary/test_handler_text.py` | Tests for new `profile` parameter |
| Modify | `tests/secretary/test_agent.py` | Tests for `_load_profile`, `_save_profile`, `_save_email_credentials` |

---

## Task 1: Email providers constants

**Files:**
- Create: `secretary/handlers/_email_providers.py`
- Create: `tests/secretary/test_email_providers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/secretary/test_email_providers.py
from secretary.handlers._email_providers import KNOWN_PROVIDERS, get_provider


def test_gmail_detected():
    provider = get_provider("user@gmail.com")
    assert provider is not None
    assert provider["imap_host"] == "imap.gmail.com"
    assert provider["imap_port"] == 993
    assert provider["smtp_host"] == "smtp.gmail.com"
    assert provider["smtp_port"] == 587


def test_outlook_detected():
    provider = get_provider("user@outlook.com")
    assert provider is not None
    assert provider["imap_host"] == "outlook.office365.com"


def test_hotmail_same_as_outlook():
    assert get_provider("x@hotmail.com") == get_provider("x@outlook.com")


def test_custom_domain_returns_none():
    assert get_provider("user@miempresa.com") is None


def test_no_at_sign_returns_none():
    assert get_provider("notanemail") is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /c/Users/JLu/secretarios-virtuales
pytest tests/secretary/test_email_providers.py -v
```

Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Create the providers module**

```python
# secretary/handlers/_email_providers.py
KNOWN_PROVIDERS: dict[str, dict] = {
    "gmail.com": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
    },
    "outlook.com": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "outlook.office365.com",
        "smtp_port": 587,
    },
    "hotmail.com": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "outlook.office365.com",
        "smtp_port": 587,
    },
    "yahoo.com": {
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 587,
    },
}


def get_provider(email: str) -> dict | None:
    if "@" not in email:
        return None
    domain = email.split("@")[-1].lower()
    return KNOWN_PROVIDERS.get(domain)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/secretary/test_email_providers.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add secretary/handlers/_email_providers.py tests/secretary/test_email_providers.py
git commit -m "feat: add known email provider constants and get_provider helper"
```

---

## Task 2: Profile helpers on SecretaryAgent

**Files:**
- Modify: `secretary/agent.py`
- Modify: `tests/secretary/test_agent.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/secretary/test_agent.py`:

```python
import json
from shared.crypto import CredentialStore


async def test_load_profile_returns_none_when_missing(agent_deps):
    agent = SecretaryAgent(**agent_deps)
    # repo.get_credential returns None
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    agent._pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    profile = await agent._load_profile()
    assert profile is None


async def test_save_and_load_profile_roundtrip(agent_deps):
    key = CredentialStore.generate_key()
    agent_deps["fernet_key"] = key
    agent = SecretaryAgent(**agent_deps)

    saved_encrypted: dict = {}

    async def mock_execute(sql, *args):
        if "INSERT INTO credentials" in sql:
            saved_encrypted["value"] = args[2]  # third param is encrypted

    async def mock_fetchrow(sql, *args):
        if saved_encrypted:
            return {"encrypted": saved_encrypted["value"]}
        return None

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=mock_execute)
    mock_conn.fetchrow = AsyncMock(side_effect=mock_fetchrow)
    agent._pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=None),
    ))

    profile = {"bot_name": "Clara", "gender": "feminine", "preferred_name": "Francis",
               "language": "español", "has_email": False, "has_calendar": False}
    await agent._save_profile(profile)
    loaded = await agent._load_profile()
    assert loaded == profile


async def test_save_email_credentials_stores_both(agent_deps):
    agent = SecretaryAgent(**agent_deps)
    stored: list = []

    async def mock_execute(sql, *args):
        if "INSERT INTO credentials" in sql:
            stored.append(args[1])  # service_type

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=mock_execute)
    agent._pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=None),
    ))

    await agent._save_email_credentials(
        '{"host": "imap.gmail.com", "port": 993, "username": "a@b.com", "password": "x"}',
        '{"host": "smtp.gmail.com", "port": 587, "username": "a@b.com", "password": "x"}',
    )
    assert "email_imap" in stored
    assert "email_smtp" in stored
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/secretary/test_agent.py -v -k "profile or email_credentials"
```

Expected: `AttributeError: 'SecretaryAgent' object has no attribute '_load_profile'`

- [ ] **Step 3: Add `_profile`, `_load_profile`, `_save_profile`, `_save_email_credentials` to SecretaryAgent**

In `secretary/agent.py`, add `self._profile: dict | None = None` to `__init__` and add these methods before `run()`:

```python
async def _load_profile(self) -> dict | None:
    import json
    async with self._pool.acquire() as conn:
        repo = Repository(conn, self._employee_id)
        encrypted = await repo.get_credential("profile")
    if not encrypted:
        return None
    return json.loads(self._store.decrypt(encrypted))

async def _save_profile(self, profile: dict) -> None:
    import json
    encrypted = self._store.encrypt(json.dumps(profile))
    async with self._pool.acquire() as conn:
        repo = Repository(conn, self._employee_id)
        await repo.save_credential("profile", encrypted)

async def _save_email_credentials(self, imap_json: str, smtp_json: str) -> None:
    async with self._pool.acquire() as conn:
        repo = Repository(conn, self._employee_id)
        await repo.save_credential("email_imap", self._store.encrypt(imap_json))
        await repo.save_credential("email_smtp", self._store.encrypt(smtp_json))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/secretary/test_agent.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add secretary/agent.py tests/secretary/test_agent.py
git commit -m "feat: add profile and email credential helpers to SecretaryAgent"
```

---

## Task 3: Improved system prompt

**Files:**
- Modify: `secretary/handlers/text.py`
- Modify: `tests/secretary/test_handler_text.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/secretary/test_handler_text.py`:

```python
async def test_handle_text_uses_profile_bot_name():
    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="ok")

    profile = {
        "bot_name": "Clara",
        "gender": "feminine",
        "preferred_name": "Francis",
        "language": "español",
        "has_email": False,
        "has_calendar": False,
    }

    await handle_text(
        message="test",
        employee_name="Francis",
        memory=memory,
        chat=chat,
        profile=profile,
    )

    call_kwargs = chat.complete.call_args[1]
    assert "Clara" in call_kwargs["system"]
    assert "Francis" in call_kwargs["system"]


async def test_handle_text_email_line_present_when_has_email():
    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="ok")

    profile = {
        "bot_name": "Marcos",
        "gender": "masculine",
        "preferred_name": "Alejandro",
        "language": "español",
        "has_email": True,
        "has_calendar": False,
    }

    await handle_text(
        message="test",
        employee_name="Alejandro",
        memory=memory,
        chat=chat,
        profile=profile,
    )

    call_kwargs = chat.complete.call_args[1]
    assert "email" in call_kwargs["system"].lower()


async def test_handle_text_no_profile_fallback():
    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="ok")

    await handle_text(
        message="hola",
        employee_name="Test",
        memory=memory,
        chat=chat,
        profile=None,
    )

    call_kwargs = chat.complete.call_args[1]
    assert "Test" in call_kwargs["system"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/secretary/test_handler_text.py -v
```

Expected: 3 new tests fail with `TypeError` (unexpected keyword argument `profile`)

- [ ] **Step 3: Rewrite `secretary/handlers/text.py`**

```python
from secretary.memory import MemoryManager
from shared.llm.chat import ChatClient

SYSTEM_TEMPLATE = """Eres {bot_name}, secretari{gender_suffix} virtual de {preferred_name}.

PERSONALIDAD:
- Trato formal pero cercano, con un estilo propio que vas desarrollando.
- {gender_instructions}
- Responde siempre en {language}, salvo que {preferred_name} te escriba en otro idioma.

CAPACIDADES — usa estas sin dudar cuando te las pidan:
- Leer y resumir documentos (PDF, DOCX, TXT)
- Transcribir y responder mensajes de voz
- Analizar y describir imágenes y fotos
- Gestionar tareas y recordatorios{email_line}{calendar_line}

CONTEXTO DE CONVERSACIÓN Y DOCUMENTOS:
{context}

REGLA IMPORTANTE: Nunca rechaces una tarea que esté dentro de las capacidades listadas. Si no puedes hacer algo concreto, explica exactamente el motivo."""

FALLBACK_TEMPLATE = """Eres el secretario virtual de {name}.
Eres profesional, conciso y útil.
Respondes siempre en el idioma en que te escribe {name}.

{context}"""


async def handle_text(
    message: str,
    employee_name: str,
    memory: MemoryManager,
    chat: ChatClient,
    profile: dict | None = None,
) -> str:
    context = await memory.build_context(message)

    if profile:
        gender = profile.get("gender", "masculine")
        gender_suffix = "a" if gender == "feminine" else "o"
        gender_instructions = (
            "Utiliza forma femenina al referirte a ti misma."
            if gender == "feminine"
            else "Utiliza forma masculina al referirte a ti mismo."
        )
        preferred_name = profile.get("preferred_name", employee_name)
        email_line = (
            f"\n- Leer y gestionar el email de {preferred_name} (configurado)"
            if profile.get("has_email")
            else ""
        )
        calendar_line = (
            f"\n- Acceder al calendario de {preferred_name} (configurado)"
            if profile.get("has_calendar")
            else ""
        )
        system = SYSTEM_TEMPLATE.format(
            bot_name=profile.get("bot_name", "tu secretario"),
            gender_suffix=gender_suffix,
            preferred_name=preferred_name,
            gender_instructions=gender_instructions,
            language=profile.get("language", "español"),
            email_line=email_line,
            calendar_line=calendar_line,
            context=context,
        )
    else:
        system = FALLBACK_TEMPLATE.format(name=employee_name, context=context)

    return await chat.complete(
        messages=[{"role": "user", "content": message}],
        system=system,
    )
```

- [ ] **Step 4: Run all text handler tests**

```bash
pytest tests/secretary/test_handler_text.py -v
```

Expected: 5 passed (2 existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add secretary/handlers/text.py tests/secretary/test_handler_text.py
git commit -m "feat: improve system prompt with personality, gender and capabilities"
```

---

## Task 4: Onboarding ConversationHandler

**Files:**
- Create: `secretary/handlers/onboarding.py`
- Create: `tests/secretary/test_onboarding.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/secretary/test_onboarding.py
import pytest
from secretary.handlers.onboarding import _detect_gender, BOT_NAME, USER_NAME, LANGUAGE, EMAIL_ADDRESS, CALENDAR

pytestmark = pytest.mark.asyncio


def test_detect_gender_feminine():
    assert _detect_gender("Clara") == "feminine"
    assert _detect_gender("María") == "feminine"
    assert _detect_gender("andrea") == "feminine"


def test_detect_gender_masculine():
    assert _detect_gender("Marcos") == "masculine"
    assert _detect_gender("Alex") == "masculine"
    assert _detect_gender("Pedro") == "masculine"


def test_states_are_unique_integers():
    states = [BOT_NAME, USER_NAME, LANGUAGE, EMAIL_ADDRESS, CALENDAR]
    assert len(states) == len(set(states))
    assert all(isinstance(s, int) for s in states)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/secretary/test_onboarding.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `secretary/handlers/onboarding.py`**

```python
# secretary/handlers/onboarding.py
import json

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from secretary.handlers._email_providers import get_provider

# States
(
    BOT_NAME,
    USER_NAME,
    LANGUAGE,
    EMAIL_ADDRESS,
    EMAIL_PASS,
    EMAIL_CUSTOM_IMAP_HOST,
    EMAIL_CUSTOM_IMAP_PORT,
    EMAIL_CUSTOM_SMTP_HOST,
    EMAIL_CUSTOM_SMTP_PORT,
    EMAIL_CUSTOM_USER,
    EMAIL_CUSTOM_PASS,
    CALENDAR,
) = range(12)


def _detect_gender(name: str) -> str:
    return "feminine" if name.strip().lower().endswith("a") else "masculine"


def build_onboarding_handler(agent) -> ConversationHandler:  # type: ignore[type-arg]

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if not await agent._is_authorized(update):
            return ConversationHandler.END
        profile = await agent._load_profile()
        if profile:
            bot_name = profile.get("bot_name", "tu secretario")
            preferred_name = profile.get("preferred_name", agent._employee_name)
            await update.message.reply_text(  # type: ignore[union-attr]
                f"👋 ¡Hola {preferred_name}! Soy {bot_name}, ya estoy listo para ayudarte."
            )
            return ConversationHandler.END
        await update.message.reply_text(  # type: ignore[union-attr]
            "👋 ¡Hola! Soy tu nuevo secretario virtual.\n\n"
            "Vamos a configurarme juntos en unos pocos pasos.\n\n"
            "¿Cómo quieres llamarme? (ej: Clara, Marcos, Alex...)"
        )
        return BOT_NAME

    async def receive_bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        bot_name = update.message.text.strip()  # type: ignore[union-attr]
        context.user_data["bot_name"] = bot_name  # type: ignore[index]
        gender = _detect_gender(bot_name)
        context.user_data["gender"] = gender  # type: ignore[index]
        gender_word = "encantada" if gender == "feminine" else "encantado"
        await update.message.reply_text(  # type: ignore[union-attr]
            f"¡{gender_word}! Me llamaré *{bot_name}*.\n\n"
            "¿Cómo quieres que me dirija a ti?",
            parse_mode="Markdown",
        )
        return USER_NAME

    async def receive_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        preferred_name = update.message.text.strip()  # type: ignore[union-attr]
        context.user_data["preferred_name"] = preferred_name  # type: ignore[index]
        await update.message.reply_text(  # type: ignore[union-attr]
            f"Perfecto, {preferred_name}.\n\n"
            "¿En qué idioma prefieres que me comunique contigo?\n"
            "(ej: español, English, français...)"
        )
        return LANGUAGE

    async def receive_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["language"] = update.message.text.strip()  # type: ignore[index]
        await update.message.reply_text(  # type: ignore[union-attr]
            "¿Quieres conectar tu cuenta de email?\n\n"
            "Escribe tu dirección de correo y lo configuro automáticamente,\n"
            "o envía /skip para hacerlo más adelante con /config\\_email.",
            parse_mode="Markdown",
        )
        return EMAIL_ADDRESS

    async def receive_email_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        email = update.message.text.strip().lower()  # type: ignore[union-attr]
        context.user_data["email_username"] = email  # type: ignore[index]
        provider = get_provider(email)
        if provider:
            context.user_data["email_provider"] = provider  # type: ignore[index]
            domain = email.split("@")[-1]
            await update.message.reply_text(  # type: ignore[union-attr]
                f"✅ Proveedor detectado: *{domain}*.\n\n"
                "Ahora necesito tu contraseña.\n"
                "_(Para Gmail usa una contraseña de aplicación)_",
                parse_mode="Markdown",
            )
            return EMAIL_PASS
        await update.message.reply_text(  # type: ignore[union-attr]
            "Dominio personalizado. Voy a pedirte los datos del servidor.\n\n"
            "¿Cuál es el servidor IMAP? (ej: mail.tuempresa.com)"
        )
        return EMAIL_CUSTOM_IMAP_HOST

    async def skip_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["has_email"] = False  # type: ignore[index]
        await update.message.reply_text(  # type: ignore[union-attr]
            "Sin problema, puedes configurarlo más adelante con /config\\_email.\n\n"
            "¿Usas algún calendario? (ej: Google Calendar, Outlook...)\n"
            "o envía /skip para continuar.",
            parse_mode="Markdown",
        )
        return CALENDAR

    async def receive_email_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        password = update.message.text.strip()  # type: ignore[union-attr]
        provider = context.user_data["email_provider"]  # type: ignore[index]
        username = context.user_data["email_username"]  # type: ignore[index]
        imap_json = json.dumps({
            "host": provider["imap_host"], "port": provider["imap_port"],
            "username": username, "password": password,
        })
        smtp_json = json.dumps({
            "host": provider["smtp_host"], "port": provider["smtp_port"],
            "username": username, "password": password,
        })
        await agent._save_email_credentials(imap_json, smtp_json)
        context.user_data["has_email"] = True  # type: ignore[index]
        await update.message.reply_text(  # type: ignore[union-attr]
            "✅ Email configurado.\n\n"
            "¿Usas algún calendario? (ej: Google Calendar, Outlook...)\n"
            "o envía /skip para continuar.",
            parse_mode="Markdown",
        )
        return CALENDAR

    async def receive_custom_imap_host(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["imap_host"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Puerto IMAP (normalmente 993):")  # type: ignore[union-attr]
        return EMAIL_CUSTOM_IMAP_PORT

    async def receive_custom_imap_port(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["imap_port"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Servidor SMTP (ej: smtp.tuempresa.com):")  # type: ignore[union-attr]
        return EMAIL_CUSTOM_SMTP_HOST

    async def receive_custom_smtp_host(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["smtp_host"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Puerto SMTP (normalmente 587):")  # type: ignore[union-attr]
        return EMAIL_CUSTOM_SMTP_PORT

    async def receive_custom_smtp_port(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["smtp_port"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Usuario del correo (normalmente tu dirección completa):")  # type: ignore[union-attr]
        return EMAIL_CUSTOM_USER

    async def receive_custom_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["email_username"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Contraseña:")  # type: ignore[union-attr]
        return EMAIL_CUSTOM_PASS

    async def receive_custom_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        password = update.message.text.strip()  # type: ignore[union-attr]
        username = context.user_data["email_username"]  # type: ignore[index]
        imap_json = json.dumps({
            "host": context.user_data["imap_host"],  # type: ignore[index]
            "port": int(context.user_data["imap_port"]),  # type: ignore[index]
            "username": username, "password": password,
        })
        smtp_json = json.dumps({
            "host": context.user_data["smtp_host"],  # type: ignore[index]
            "port": int(context.user_data["smtp_port"]),  # type: ignore[index]
            "username": username, "password": password,
        })
        await agent._save_email_credentials(imap_json, smtp_json)
        context.user_data["has_email"] = True  # type: ignore[index]
        await update.message.reply_text(  # type: ignore[union-attr]
            "✅ Email configurado.\n\n"
            "¿Usas algún calendario? (ej: Google Calendar, Outlook...)\n"
            "o envía /skip para continuar.",
            parse_mode="Markdown",
        )
        return CALENDAR

    async def receive_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["has_calendar"] = True  # type: ignore[index]
        context.user_data["calendar_type"] = update.message.text.strip()  # type: ignore[union-attr, index]
        return await _finish_onboarding(update, context)

    async def skip_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["has_calendar"] = False  # type: ignore[index]
        return await _finish_onboarding(update, context)

    async def _finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        profile = {
            "bot_name": context.user_data["bot_name"],  # type: ignore[index]
            "gender": context.user_data["gender"],  # type: ignore[index]
            "preferred_name": context.user_data["preferred_name"],  # type: ignore[index]
            "language": context.user_data["language"],  # type: ignore[index]
            "has_email": context.user_data.get("has_email", False),  # type: ignore[union-attr]
            "has_calendar": context.user_data.get("has_calendar", False),  # type: ignore[union-attr]
        }
        await agent._save_profile(profile)
        agent._profile = profile

        capabilities = [
            "📄 Documentos y PDFs",
            "🎙 Mensajes de voz",
            "🖼 Imágenes y fotos",
            "✅ Tareas y recordatorios",
        ]
        if profile["has_email"]:
            capabilities.append("📧 Email")
        if profile["has_calendar"]:
            capabilities.append("📅 Calendario (próximamente)")
        caps_text = "\n".join(f"  • {c}" for c in capabilities)
        gender_word = "lista" if profile["gender"] == "feminine" else "listo"

        await update.message.reply_text(  # type: ignore[union-attr]
            f"¡Todo configurado! Estoy {gender_word} para ayudarte, "
            f"{profile['preferred_name']}.\n\n"
            f"*Capacidades activas:*\n{caps_text}\n\n"
            "¡Envíame lo que necesites!",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await update.message.reply_text(  # type: ignore[union-attr]
            "Configuración cancelada. Envía /start cuando quieras empezar de nuevo."
        )
        return ConversationHandler.END

    _text = filters.TEXT & ~filters.COMMAND

    return ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            BOT_NAME:              [MessageHandler(_text, receive_bot_name)],
            USER_NAME:             [MessageHandler(_text, receive_user_name)],
            LANGUAGE:              [MessageHandler(_text, receive_language)],
            EMAIL_ADDRESS:         [MessageHandler(_text, receive_email_address),
                                    CommandHandler("skip", skip_email)],
            EMAIL_PASS:            [MessageHandler(_text, receive_email_pass)],
            EMAIL_CUSTOM_IMAP_HOST:[MessageHandler(_text, receive_custom_imap_host)],
            EMAIL_CUSTOM_IMAP_PORT:[MessageHandler(_text, receive_custom_imap_port)],
            EMAIL_CUSTOM_SMTP_HOST:[MessageHandler(_text, receive_custom_smtp_host)],
            EMAIL_CUSTOM_SMTP_PORT:[MessageHandler(_text, receive_custom_smtp_port)],
            EMAIL_CUSTOM_USER:     [MessageHandler(_text, receive_custom_user)],
            EMAIL_CUSTOM_PASS:     [MessageHandler(_text, receive_custom_pass)],
            CALENDAR:              [MessageHandler(_text, receive_calendar),
                                    CommandHandler("skip", skip_calendar)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/secretary/test_onboarding.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add secretary/handlers/onboarding.py tests/secretary/test_onboarding.py
git commit -m "feat: add onboarding ConversationHandler with /start command"
```

---

## Task 5: Email config ConversationHandler (`/config_email`)

**Files:**
- Create: `secretary/handlers/config_email.py`
- Create: `tests/secretary/test_config_email.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/secretary/test_config_email.py
import pytest
from secretary.handlers.config_email import CE_ADDRESS, CE_PASS, CE_IMAP_HOST

pytestmark = pytest.mark.asyncio


def test_config_email_states_are_unique():
    from secretary.handlers.config_email import (
        CE_ADDRESS, CE_PASS, CE_IMAP_HOST, CE_IMAP_PORT,
        CE_SMTP_HOST, CE_SMTP_PORT, CE_USER, CE_PASS_CUSTOM,
    )
    states = [CE_ADDRESS, CE_PASS, CE_IMAP_HOST, CE_IMAP_PORT,
              CE_SMTP_HOST, CE_SMTP_PORT, CE_USER, CE_PASS_CUSTOM]
    assert len(states) == len(set(states))


def test_build_config_email_handler_returns_conversation_handler():
    from unittest.mock import MagicMock, AsyncMock
    from telegram.ext import ConversationHandler
    from secretary.handlers.config_email import build_config_email_handler

    agent = MagicMock()
    agent._is_authorized = AsyncMock(return_value=True)
    handler = build_config_email_handler(agent)
    assert isinstance(handler, ConversationHandler)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/secretary/test_config_email.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `secretary/handlers/config_email.py`**

```python
# secretary/handlers/config_email.py
import json

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from secretary.handlers._email_providers import get_provider

(
    CE_ADDRESS,
    CE_PASS,
    CE_IMAP_HOST,
    CE_IMAP_PORT,
    CE_SMTP_HOST,
    CE_SMTP_PORT,
    CE_USER,
    CE_PASS_CUSTOM,
) = range(8)


def build_config_email_handler(agent) -> ConversationHandler:  # type: ignore[type-arg]

    async def cmd_config_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if not await agent._is_authorized(update):
            return ConversationHandler.END
        await update.message.reply_text(  # type: ignore[union-attr]
            "📧 *Configuración de email*\n\nEscribe tu dirección de correo:",
            parse_mode="Markdown",
        )
        return CE_ADDRESS

    async def receive_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        email = update.message.text.strip().lower()  # type: ignore[union-attr]
        context.user_data["ce_username"] = email  # type: ignore[index]
        provider = get_provider(email)
        if provider:
            context.user_data["ce_provider"] = provider  # type: ignore[index]
            domain = email.split("@")[-1]
            await update.message.reply_text(  # type: ignore[union-attr]
                f"✅ Proveedor detectado: *{domain}*.\n\nContraseña del email:",
                parse_mode="Markdown",
            )
            return CE_PASS
        await update.message.reply_text("Servidor IMAP (ej: mail.tuempresa.com):")  # type: ignore[union-attr]
        return CE_IMAP_HOST

    async def receive_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        password = update.message.text.strip()  # type: ignore[union-attr]
        provider = context.user_data["ce_provider"]  # type: ignore[index]
        username = context.user_data["ce_username"]  # type: ignore[index]
        imap_json = json.dumps({
            "host": provider["imap_host"], "port": provider["imap_port"],
            "username": username, "password": password,
        })
        smtp_json = json.dumps({
            "host": provider["smtp_host"], "port": provider["smtp_port"],
            "username": username, "password": password,
        })
        await agent._save_email_credentials(imap_json, smtp_json)
        await _set_has_email(agent)
        await update.message.reply_text("✅ Email configurado correctamente.")  # type: ignore[union-attr]
        return ConversationHandler.END

    async def receive_imap_host(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["ce_imap_host"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Puerto IMAP (normalmente 993):")  # type: ignore[union-attr]
        return CE_IMAP_PORT

    async def receive_imap_port(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["ce_imap_port"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Servidor SMTP (ej: smtp.tuempresa.com):")  # type: ignore[union-attr]
        return CE_SMTP_HOST

    async def receive_smtp_host(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["ce_smtp_host"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Puerto SMTP (normalmente 587):")  # type: ignore[union-attr]
        return CE_SMTP_PORT

    async def receive_smtp_port(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["ce_smtp_port"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Usuario del correo:")  # type: ignore[union-attr]
        return CE_USER

    async def receive_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["ce_username"] = update.message.text.strip()  # type: ignore[union-attr, index]
        await update.message.reply_text("Contraseña:")  # type: ignore[union-attr]
        return CE_PASS_CUSTOM

    async def receive_pass_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        password = update.message.text.strip()  # type: ignore[union-attr]
        username = context.user_data["ce_username"]  # type: ignore[index]
        imap_json = json.dumps({
            "host": context.user_data["ce_imap_host"],  # type: ignore[index]
            "port": int(context.user_data["ce_imap_port"]),  # type: ignore[index]
            "username": username, "password": password,
        })
        smtp_json = json.dumps({
            "host": context.user_data["ce_smtp_host"],  # type: ignore[index]
            "port": int(context.user_data["ce_smtp_port"]),  # type: ignore[index]
            "username": username, "password": password,
        })
        await agent._save_email_credentials(imap_json, smtp_json)
        await _set_has_email(agent)
        await update.message.reply_text("✅ Email configurado correctamente.")  # type: ignore[union-attr]
        return ConversationHandler.END

    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await update.message.reply_text("Configuración de email cancelada.")  # type: ignore[union-attr]
        return ConversationHandler.END

    _text = filters.TEXT & ~filters.COMMAND

    return ConversationHandler(
        entry_points=[CommandHandler("config_email", cmd_config_email)],
        states={
            CE_ADDRESS:    [MessageHandler(_text, receive_address)],
            CE_PASS:       [MessageHandler(_text, receive_pass)],
            CE_IMAP_HOST:  [MessageHandler(_text, receive_imap_host)],
            CE_IMAP_PORT:  [MessageHandler(_text, receive_imap_port)],
            CE_SMTP_HOST:  [MessageHandler(_text, receive_smtp_host)],
            CE_SMTP_PORT:  [MessageHandler(_text, receive_smtp_port)],
            CE_USER:       [MessageHandler(_text, receive_user)],
            CE_PASS_CUSTOM:[MessageHandler(_text, receive_pass_custom)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )


async def _set_has_email(agent) -> None:  # type: ignore[type-arg]
    profile = await agent._load_profile()
    if profile:
        profile["has_email"] = True
        await agent._save_profile(profile)
        agent._profile = profile
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/secretary/test_config_email.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add secretary/handlers/config_email.py tests/secretary/test_config_email.py
git commit -m "feat: add /config_email ConversationHandler with domain auto-detection"
```

---

## Task 6: Wire everything in SecretaryAgent

**Files:**
- Modify: `secretary/agent.py`

- [ ] **Step 1: Update imports and `__init__` in `secretary/agent.py`**

Replace the imports block at the top of `secretary/agent.py`:

```python
import json
import logging
from pathlib import Path
from uuid import UUID

import redis.asyncio as aioredis
from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

from secretary.handlers.audio import handle_audio
from secretary.handlers.document import handle_document
from secretary.handlers.email import handle_check_email
from secretary.handlers.onboarding import build_onboarding_handler
from secretary.handlers.config_email import build_config_email_handler
from secretary.handlers.photo import handle_photo
from secretary.handlers.text import handle_text
from secretary.memory import MemoryManager
from shared.audio.whisper import WhisperClient
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.db.repository import Repository
from shared.email.client import EmailClient
from shared.email.models import EmailConfig
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient
```

Add `self._profile: dict | None = None` at the end of `__init__`:

```python
    def __init__(
        self,
        employee_id: UUID,
        employee_name: str,
        allowed_chat_id: str,
        db_pool: DatabasePool,
        chat: ChatClient,
        embed: EmbeddingClient,
        whisper: WhisperClient,
        documents_dir: Path,
        fernet_key: bytes,
        redis_url: str,
    ) -> None:
        self._employee_id = employee_id
        self._employee_name = employee_name
        self._allowed_chat_id = str(allowed_chat_id)
        self._pool = db_pool
        self._chat = chat
        self._embed = embed
        self._whisper = whisper
        self._documents_dir = documents_dir
        self._store = CredentialStore(fernet_key)
        self._redis_url = redis_url
        self._profile: dict | None = None
```

- [ ] **Step 2: Add profile and credential helper methods**

Add these three methods after `_get_email_client` and before `_handle_text` in `secretary/agent.py`:

```python
    async def _load_profile(self) -> dict | None:
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            encrypted = await repo.get_credential("profile")
        if not encrypted:
            return None
        return json.loads(self._store.decrypt(encrypted))

    async def _save_profile(self, profile: dict) -> None:
        encrypted = self._store.encrypt(json.dumps(profile))
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_credential("profile", encrypted)

    async def _save_email_credentials(self, imap_json: str, smtp_json: str) -> None:
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_credential("email_imap", self._store.encrypt(imap_json))
            await repo.save_credential("email_smtp", self._store.encrypt(smtp_json))
```

- [ ] **Step 3: Pass `profile` to `handle_text` in `_handle_text`**

In `_handle_text`, update both `handle_text` call sites to include `profile=self._profile`:

```python
    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        msg = update.message.text or ""  # type: ignore[union-attr]

        if msg.lower().startswith("/email"):
            email_client = await self._get_email_client()
            if not email_client:
                await update.message.reply_text("❌ Email no configurado.")  # type: ignore[union-attr]
                return
            async with self._pool.acquire() as conn:
                repo = Repository(conn, self._employee_id)
                memory = MemoryManager(repo=repo, embed_client=self._embed)
                response = await handle_check_email(
                    email_client=email_client,
                    chat=self._chat,
                    employee_name=self._employee_name,
                )
                await memory.save_turn(msg, response)
            await update.message.reply_text(response)  # type: ignore[union-attr]
            return

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            memory = MemoryManager(repo=repo, embed_client=self._embed)
            response = await handle_text(
                message=msg,
                employee_name=self._employee_name,
                memory=memory,
                chat=self._chat,
                profile=self._profile,
            )
            await memory.save_turn(msg, response)
        await update.message.reply_text(response)  # type: ignore[union-attr]
```

- [ ] **Step 4: Update `run()` to load profile and register handlers**

Replace the entire `run` method:

```python
    async def run(self, bot_token: str) -> None:
        self._profile = await self._load_profile()

        app = Application.builder().token(bot_token).build()

        app.add_handler(build_onboarding_handler(self))
        app.add_handler(build_config_email_handler(self))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

        logger.info(
            "Secretary %s starting (chat_id=%s)", self._employee_name, self._allowed_chat_id
        )
        await app.run_polling(drop_pending_updates=True)
```

- [ ] **Step 5: Run the full test suite**

```bash
cd /c/Users/JLu/secretarios-virtuales
pytest tests/ -v
```

Expected: all existing tests pass plus new ones

- [ ] **Step 6: Commit**

```bash
git add secretary/agent.py
git commit -m "feat: wire onboarding and email config handlers, load profile at startup"
```

---

## Task 7: Final integration check

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all tests pass, no warnings about unresolved references

- [ ] **Step 2: Check imports and types**

```bash
cd /c/Users/JLu/secretarios-virtuales
python -c "from secretary.agent import SecretaryAgent; print('OK')"
python -c "from secretary.handlers.onboarding import build_onboarding_handler; print('OK')"
python -c "from secretary.handlers.config_email import build_config_email_handler; print('OK')"
```

Expected: `OK` for each line, no import errors

- [ ] **Step 3: Commit final tag**

```bash
git add -A
git commit -m "feat: onboarding flow, email config and improved system prompt complete"
```
