import pytest
from unittest.mock import MagicMock, AsyncMock
from telegram.ext import ConversationHandler
from secretary.handlers.config_email import build_config_email_handler


def test_config_email_states_are_unique():
    from secretary.handlers.config_email import (
        CE_ADDRESS, CE_PASS, CE_IMAP_HOST, CE_IMAP_PORT,
        CE_SMTP_HOST, CE_SMTP_PORT, CE_USER, CE_PASS_CUSTOM,
    )
    states = [CE_ADDRESS, CE_PASS, CE_IMAP_HOST, CE_IMAP_PORT,
              CE_SMTP_HOST, CE_SMTP_PORT, CE_USER, CE_PASS_CUSTOM]
    assert len(states) == len(set(states))


def test_build_config_email_handler_returns_conversation_handler():
    agent = MagicMock()
    agent._is_authorized = AsyncMock(return_value=True)
    handler = build_config_email_handler(agent)
    assert isinstance(handler, ConversationHandler)
