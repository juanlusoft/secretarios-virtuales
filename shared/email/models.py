from dataclasses import dataclass


@dataclass
class EmailConfig:
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    username: str
    password: str


@dataclass
class EmailMessage:
    uid: str
    sender: str
    subject: str
    body: str
    date: str
