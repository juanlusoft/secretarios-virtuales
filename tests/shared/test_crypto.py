from shared.crypto import CredentialStore


def test_encrypt_decrypt_roundtrip():
    key = CredentialStore.generate_key()
    store = CredentialStore(key)
    original = "mi_token_secreto_12345"
    encrypted = store.encrypt(original)
    assert encrypted != original
    assert store.decrypt(encrypted) == original


def test_different_values_produce_different_ciphertext():
    key = CredentialStore.generate_key()
    store = CredentialStore(key)
    e1 = store.encrypt("valor1")
    e2 = store.encrypt("valor2")
    assert e1 != e2
