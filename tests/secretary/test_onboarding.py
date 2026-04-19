import pytest
from secretary.handlers.onboarding import (
    _detect_gender,
    BOT_NAME, USER_NAME, LANGUAGE, EMAIL_ADDRESS, EMAIL_PASS,
    EMAIL_CUSTOM_IMAP_HOST, EMAIL_CUSTOM_IMAP_PORT,
    EMAIL_CUSTOM_SMTP_HOST, EMAIL_CUSTOM_SMTP_PORT,
    EMAIL_CUSTOM_USER, EMAIL_CUSTOM_PASS, CALENDAR,
)


def test_detect_gender_feminine():
    assert _detect_gender("Clara") == "feminine"
    assert _detect_gender("María") == "feminine"
    assert _detect_gender("andrea") == "feminine"


def test_detect_gender_masculine():
    assert _detect_gender("Marcos") == "masculine"
    assert _detect_gender("Alex") == "masculine"
    assert _detect_gender("Pedro") == "masculine"


def test_states_are_unique_integers():
    states = [
        BOT_NAME, USER_NAME, LANGUAGE, EMAIL_ADDRESS, EMAIL_PASS,
        EMAIL_CUSTOM_IMAP_HOST, EMAIL_CUSTOM_IMAP_PORT,
        EMAIL_CUSTOM_SMTP_HOST, EMAIL_CUSTOM_SMTP_PORT,
        EMAIL_CUSTOM_USER, EMAIL_CUSTOM_PASS, CALENDAR,
    ]
    assert len(states) == 12
    assert len(states) == len(set(states))
    assert all(isinstance(s, int) for s in states)
