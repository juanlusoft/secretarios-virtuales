from pathlib import Path
from datetime import datetime, timezone

import pytest

from shared.vault.parser import NoteData, parse_note


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_plain_note(tmp_path):
    p = _write(tmp_path, "hola.md", "# Hola\n\nEsto es una nota.")
    note = parse_note(p, vault_root=tmp_path)
    assert note.vault_path == "hola.md"
    assert note.title == "hola"
    assert note.content_text == "# Hola\n\nEsto es una nota."
    assert note.tags == []
    assert isinstance(note.modified_at, datetime)


def test_parse_frontmatter(tmp_path):
    content = "---\ntitle: Mi nota\ntags: [trabajo, urgente]\n---\n\nContenido aquí."
    p = _write(tmp_path, "nota.md", content)
    note = parse_note(p, vault_root=tmp_path)
    assert note.title == "Mi nota"
    assert note.tags == ["trabajo", "urgente"]
    assert note.content_text == "Contenido aquí."


def test_cleans_wikilinks(tmp_path):
    p = _write(tmp_path, "wikilinks.md", "Habla con [[Pedro Sánchez]] sobre [[reunión|la reunión]].")
    note = parse_note(p, vault_root=tmp_path)
    assert "[[" not in note.content_text
    assert "Pedro Sánchez" in note.content_text
    assert "la reunión" in note.content_text


def test_cleans_hashtags(tmp_path):
    p = _write(tmp_path, "tags.md", "Este es un texto con #trabajo y #urgente como etiquetas.")
    note = parse_note(p, vault_root=tmp_path)
    assert "#trabajo" not in note.content_text
    assert "#urgente" not in note.content_text
    assert "Este es un texto con" in note.content_text


def test_subdirectory_vault_path(tmp_path):
    subdir = tmp_path / "proyectos"
    subdir.mkdir()
    p = _write(subdir, "web.md", "Proyecto web.")
    note = parse_note(p, vault_root=tmp_path)
    assert note.vault_path == "proyectos/web.md"


def test_frontmatter_tags_string(tmp_path):
    content = "---\ntitle: Test\ntags: trabajo, urgente\n---\nContenido."
    p = _write(tmp_path, "t.md", content)
    note = parse_note(p, vault_root=tmp_path)
    assert "trabajo" in note.tags
    assert "urgente" in note.tags
