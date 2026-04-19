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
