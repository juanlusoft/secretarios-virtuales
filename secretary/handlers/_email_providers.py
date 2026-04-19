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
