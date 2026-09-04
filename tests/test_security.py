"""Unit tests cho module security (Envelope Encryption & Masking)."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from core.security import (
    decrypt_integration_key,
    derive_fernet_key,
    encrypt_integration_key,
    mask_api_key,
)


def test_derive_fernet_key_from_secret():
    secret = "my-plain-secret"
    derived = derive_fernet_key(secret)
    # Phải là valid Fernet key (32 bytes urlsafe base64)
    fernet = Fernet(derived)
    assert fernet is not None


def test_derive_fernet_key_preserves_valid_fernet_key():
    valid = Fernet.generate_key().decode("utf-8")
    derived = derive_fernet_key(valid)
    assert derived == valid.encode("utf-8")


def test_envelope_encryption_roundtrip():
    kek_secret = "master-kek-secret-key"
    raw_api_key = "sk-test-1234567890abcdef"

    enc = encrypt_integration_key(raw_api_key, kek_secret)
    assert enc.encrypted_api_key != ""
    assert enc.encrypted_dek != ""
    assert enc.encrypted_api_key != raw_api_key

    decrypted = decrypt_integration_key(
        enc.encrypted_api_key,
        enc.encrypted_dek,
        kek_secret,
    )
    assert decrypted == raw_api_key


def test_envelope_encryption_unique_deks():
    kek_secret = "master-kek-secret-key"
    raw_api_key = "sk-same-key"

    enc1 = encrypt_integration_key(raw_api_key, kek_secret)
    enc2 = encrypt_integration_key(raw_api_key, kek_secret)

    # Mỗi lần mã hóa phải sinh DEK riêng biệt (ciphertext khác nhau)
    assert enc1.encrypted_dek != enc2.encrypted_dek
    assert enc1.encrypted_api_key != enc2.encrypted_api_key

    res1 = decrypt_integration_key(enc1.encrypted_api_key, enc1.encrypted_dek, kek_secret)
    res2 = decrypt_integration_key(enc2.encrypted_api_key, enc2.encrypted_dek, kek_secret)
    assert res1 == raw_api_key
    assert res2 == raw_api_key

def test_envelope_decryption_wrong_kek_fails():
    enc = encrypt_integration_key("sk-secret", "correct-kek")
    with pytest.raises(ValueError, match="Không thể giải mã API key"):
        decrypt_integration_key(enc.encrypted_api_key, enc.encrypted_dek, "wrong-kek")


def test_empty_api_key_handling():
    enc = encrypt_integration_key("", "kek")
    assert enc.encrypted_api_key == ""
    assert enc.encrypted_dek == ""

    decrypted = decrypt_integration_key("", "", "kek")
    assert decrypted == ""


def test_mask_api_key():
    long_key = "sk-9a03f0f12f81f9adc45c0708a2d64ff2ae2a82b22a83cadd30fa1947332d063f"
    assert mask_api_key(long_key) == "sk-9a03...063f"
    assert mask_api_key("sk-short") == "••••••••"
    assert mask_api_key("sk-abcdefgh1234") == "sk-abcd...1234"
