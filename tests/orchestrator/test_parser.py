from orchestrator.parser import (
    CreateSecretaryCommand,
    DestroySecretaryCommand,
    ListSecretariesCommand,
    SendMessageCommand,
    parse_command,
)


def test_parse_create_command():
    cmd = parse_command("crea secretario para Alejandro, token: 123abc456, chatid: 789")
    assert isinstance(cmd, CreateSecretaryCommand)
    assert cmd.name == "Alejandro"
    assert cmd.telegram_token == "123abc456"
    assert cmd.telegram_chat_id == "789"


def test_parse_destroy_command():
    cmd = parse_command("destruye secretario de María")
    assert isinstance(cmd, DestroySecretaryCommand)
    assert cmd.name == "María"


def test_parse_send_message_command():
    cmd = parse_command("avisa a Pedro que hay reunión mañana a las 10h")
    assert isinstance(cmd, SendMessageCommand)
    assert cmd.name == "Pedro"
    assert "reunión" in cmd.message


def test_parse_list_command():
    cmd = parse_command("lista los secretarios")
    assert isinstance(cmd, ListSecretariesCommand)


def test_returns_none_for_unknown():
    cmd = parse_command("hola, ¿cómo estás?")
    assert cmd is None


def test_parse_create_without_chatid():
    cmd = parse_command("crea secretario para Juan, token: tok123")
    assert isinstance(cmd, CreateSecretaryCommand)
    assert cmd.name == "Juan"
    assert cmd.telegram_token == "tok123"
