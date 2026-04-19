# Design: Onboarding, Email Config & System Prompt

**Date:** 2026-04-19  
**Scope:** Items 1-3 from pendiente_secretarios.md  
**Approach:** Option A — linear ConversationHandler with profile stored in `credentials` table

---

## 1. Onboarding Flow (`/start`)

### Trigger
When an employee sends `/start` for the first time (no `profile` credential in DB).  
On subsequent `/start`, the bot sends a welcome-back message and exits.

### States

| State | Bot asks | User responds | Next state |
|---|---|---|---|
| `ONBOARDING_BOT_NAME` | "¿Cómo quieres llamarme?" | Name for the bot | `ONBOARDING_USER_NAME` |
| `ONBOARDING_USER_NAME` | "¿Cómo quieres que te llame yo?" | User's preferred name | `ONBOARDING_LANGUAGE` |
| `ONBOARDING_LANGUAGE` | "¿En qué idioma prefieres que me comunique?" | Language | `ONBOARDING_EMAIL` |
| `ONBOARDING_EMAIL` | "¿Quieres conectar tu email? (o /skip)" | Email address or `/skip` | `ONBOARDING_EMAIL_PASS` or `ONBOARDING_CALENDAR` |
| `ONBOARDING_EMAIL_PASS` | "Contraseña del email" | Password | `ONBOARDING_CALENDAR` |
| `ONBOARDING_EMAIL_CUSTOM_*` | IMAP host → IMAP port → SMTP host → SMTP port → user → pass | Individual fields | `ONBOARDING_CALENDAR` |
| `ONBOARDING_CALENDAR` | "¿Usas Google Calendar u otro? (o /skip)" | Calendar info or `/skip` | `ONBOARDING_DONE` |
| `ONBOARDING_DONE` | Summary + capabilities | — | `END` |

### Email domain detection

Known providers are auto-configured (no manual host entry needed):

| Domain | IMAP | SMTP |
|---|---|---|
| `@gmail.com` | imap.gmail.com:993 | smtp.gmail.com:587 |
| `@outlook.com`, `@hotmail.com` | outlook.office365.com:993 | outlook.office365.com:587 |
| `@yahoo.com` | imap.mail.yahoo.com:993 | smtp.mail.yahoo.com:587 |
| Custom domain | Ask: IMAP host, IMAP port, SMTP host, SMTP port, username, password |

For known providers: ask only for the email address and password.

### Gender detection

The bot name chosen by the user determines grammatical gender in the system prompt:
- Ends in `-a` (case-insensitive) → feminine
- Otherwise → masculine
- Gender is stored in the profile and used in the system prompt to adapt all bot self-references.

### Calendar (phase 2)

During onboarding the bot asks about calendar. If the user confirms they use one, `has_calendar: true` is stored in the profile so the system prompt acknowledges it. Actual calendar API integration is a future task.

### `/skip` command

Available at any optional step (email, calendar). Moves to the next state immediately.

### `/cancel` command

Available at any point. Exits the ConversationHandler without saving the profile. The employee can restart with `/start`.

---

## 2. Post-onboarding Email Reconfiguration

A separate `ConversationHandler` triggered by `/config_email`:
- Same domain-detection logic as onboarding
- Overwrites existing `email_imap` and `email_smtp` credentials
- Confirms success and updates the `has_email` flag in the profile

---

## 3. System Prompt

**Template** (in `secretary/handlers/text.py`):

```
Eres {bot_name}, secretario{gender_suffix} virtual de {preferred_name}.

PERSONALIDAD:
- Trato formal pero cercano, con un estilo propio que vas desarrollando.
- {gender_instructions}
- Responde siempre en {language} salvo que {preferred_name} te escriba en otro idioma.

CAPACIDADES — usa estas sin dudar cuando te lo pidan:
- Leer y resumir documentos (PDF, DOCX, TXT)
- Transcribir y responder mensajes de voz
- Analizar y describir imágenes y fotos
- Gestionar tareas y recordatorios
{email_line}
{calendar_line}

CONTEXTO DE CONVERSACIÓN Y DOCUMENTOS:
{context}

REGLA IMPORTANTE: Nunca rechaces una tarea que esté dentro de las capacidades listadas. Si no puedes hacer algo concreto, explica exactamente el motivo.
```

- `{email_line}` → "- Leer y gestionar el email de {preferred_name} (configurado)" if `has_email`, else omitted
- `{calendar_line}` → "- Acceder al calendario de {preferred_name} (configurado)" if `has_calendar`, else omitted
- `{gender_suffix}` → `"a"` if feminine, `""` if masculine
- `{gender_instructions}` → e.g. "Utiliza forma femenina al referirte a ti misma."
- Fallback when no profile exists: current minimal prompt (no regression)

---

## 4. Data Model

No DB migration required. Profile stored in `credentials` table:

```json
{
  "bot_name": "Clara",
  "gender": "feminine",
  "preferred_name": "Francis",
  "language": "español",
  "has_email": true,
  "has_calendar": false
}
```

- `service_type = 'profile'`
- Encrypted with Fernet (same as all other credentials)
- Loaded once at `SecretaryAgent.run()` startup

---

## 5. Code Changes

| File | Change |
|---|---|
| `secretary/handlers/onboarding.py` | New — ConversationHandler states and handlers |
| `secretary/handlers/config_email.py` | New — `/config_email` ConversationHandler |
| `secretary/handlers/text.py` | Update `SYSTEM_TEMPLATE` and `handle_text` signature |
| `secretary/agent.py` | Load profile at startup; register both ConversationHandlers before generic handlers |
| `shared/db/repository.py` | Add `get_profile()` and `save_profile()` methods |

---

## 6. Out of Scope (this spec)

- Actual Google Calendar API integration (phase 2)
- WhatsApp integration (phase 2)
- Obsidian vault integration (phase 2)
- Sending email (stub exists, not wired)
