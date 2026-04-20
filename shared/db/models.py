from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Employee:
    id: UUID
    name: str
    telegram_chat_id: str | None
    is_orchestrator: bool
    is_active: bool
    created_at: datetime


@dataclass
class Conversation:
    id: UUID
    employee_id: UUID
    role: str
    content: str
    source: str
    created_at: datetime


@dataclass
class Document:
    id: UUID
    employee_id: UUID
    filename: str
    filepath: str
    content_text: str | None
    mime_type: str | None
    created_at: datetime


@dataclass
class Credential:
    id: UUID
    employee_id: UUID
    service_type: str
    encrypted: str


@dataclass
class Task:
    id: UUID
    employee_id: UUID
    title: str
    description: str | None
    status: str
    created_at: datetime


@dataclass
class VaultNote:
    id: UUID
    employee_id: UUID
    source: str
    vault_path: str
    title: str | None
    tags: list[str]
    content_text: str | None
    modified_at: datetime
    indexed_at: datetime
