from cryptography.fernet import Fernet


class CredentialStore:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        return self._fernet.decrypt(encrypted.encode()).decode()

    @staticmethod
    def generate_key() -> bytes:
        return Fernet.generate_key()
