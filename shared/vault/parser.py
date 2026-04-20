from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

_WIKILINK_ALIAS_RE = re.compile(r"\[\[([^\|\]]+)\|([^\]]+)\]\]")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_HASHTAG_RE = re.compile(r"\B#\w+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


@dataclass
class NoteData:
    vault_path: str
    title: str
    tags: list[str] = field(default_factory=list)
    content_text: str = ""
    modified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def parse_note(path: Path, vault_root: Path) -> NoteData:
    vault_path = str(path.relative_to(vault_root)).replace("\\", "/")
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    post = frontmatter.loads(path.read_text(encoding="utf-8", errors="replace"))

    title: str = post.get("title") or path.stem

    raw_tags = post.get("tags", [])
    if isinstance(raw_tags, str):
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    elif isinstance(raw_tags, list):
        tags = [str(t).strip() for t in raw_tags if str(t).strip()]
    else:
        tags = []

    body: str = post.content
    body = _WIKILINK_ALIAS_RE.sub(r"\2", body)
    body = _WIKILINK_RE.sub(r"\1", body)
    body = _HASHTAG_RE.sub("", body)
    body = _BLANK_LINES_RE.sub("\n\n", body).strip()

    return NoteData(
        vault_path=vault_path,
        title=title,
        tags=tags,
        content_text=body,
        modified_at=mtime,
    )
