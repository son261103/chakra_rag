"""Mã hóa bảo vệ API key của các tích hợp LLM: Envelope Encryption (KEK/DEK).

Cơ chế:
1. KEK (Key Encryption Key): Khóa mã hóa chủ được lưu trong biến môi trường `ENCRYPTION_KEY` (.env).
2. DEK (Data Encryption Key): Mỗi tích hợp sinh một khóa ngẫu nhiên riêng (Fernet key).
3. Trong bảng SQLite:
   - `encrypted_dek`: Khóa giải mã DEK của tích hợp đó, được mã hóa bằng KEK từ .env.
   - `encrypted_api_key`: API key của tích hợp đó, được mã hóa bằng DEK.
4. Khi sử dụng:
   - Dùng KEK từ .env giải mã `encrypted_dek` -> lấy DEK.
   - Dùng DEK giải mã `encrypted_api_key` -> lấy raw API key phục vụ gọi provider.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import NamedTuple

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class EncryptedPair(NamedTuple):
    encrypted_api_key: str
    encrypted_dek: str


def derive_fernet_key(secret: str) -> bytes:
    """Chuyển secret bất kỳ thành khóa Fernet 32 bytes (URL-safe base64)."""
    raw_secret = (secret or "chakra-default-secret-encryption-key-2026").strip()
    try:
        decoded = base64.urlsafe_b64decode(raw_secret.encode("utf-8"))
        if len(decoded) == 32:
            return raw_secret.encode("utf-8")
    except Exception:
        pass
    # Dùng SHA-256 để chuẩn hóa thành 32 bytes bất kể độ dài secret đầu vào
    digest = hashlib.sha256(raw_secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def generate_dek() -> bytes:
    """Sinh khóa DEK ngẫu nhiên cho một tích hợp."""
    return Fernet.generate_key()


def encrypt_integration_key(api_key: str, kek_secret: str) -> EncryptedPair:
    """Mã hóa API key theo cơ chế envelope encryption.

    Sinh DEK mới -> mã hóa DEK bằng KEK -> mã hóa API key bằng DEK.
    Trả về (encrypted_api_key, encrypted_dek).
    """
    clean_key = (api_key or "").strip()
    if not clean_key:
        return EncryptedPair(encrypted_api_key="", encrypted_dek="")

    kek = derive_fernet_key(kek_secret)
    kek_fernet = Fernet(kek)

    dek = generate_dek()
    encrypted_dek = kek_fernet.encrypt(dek).decode("utf-8")

    dek_fernet = Fernet(dek)
    encrypted_api_key = dek_fernet.encrypt(clean_key.encode("utf-8")).decode("utf-8")

    return EncryptedPair(
        encrypted_api_key=encrypted_api_key,
        encrypted_dek=encrypted_dek,
    )


def decrypt_integration_key(encrypted_api_key: str, encrypted_dek: str, kek_secret: str) -> str:
    """Giải mã API key: dùng KEK từ .env giải mã DEK, sau đó dùng DEK giải mã API key."""
    enc_key = (encrypted_api_key or "").strip()
    enc_dek = (encrypted_dek or "").strip()
    if not enc_key or not enc_dek:
        return ""

    try:
        kek = derive_fernet_key(kek_secret)
        kek_fernet = Fernet(kek)

        dek = kek_fernet.decrypt(enc_dek.encode("utf-8"))
        dek_fernet = Fernet(dek)

        raw_api_key = dek_fernet.decrypt(enc_key.encode("utf-8")).decode("utf-8")
        return raw_api_key
    except InvalidToken:
        logger.error("Giải mã API key thất bại: sai ENCRYPTION_KEY hoặc dữ liệu bị biến dạng.")
        raise ValueError("Không thể giải mã API key với khóa ENCRYPTION_KEY hiện tại.") from None
    except Exception as exc:
        logger.exception("Lỗi không xác định khi giải mã API key: %s", exc)
        raise ValueError(f"Lỗi giải mã API key: {exc}") from exc


def mask_api_key(api_key: str) -> str:
    """Che bớt API key để hiển thị an toàn trên UI (ví dụ: sk-9a03...063f)."""
    key = (api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    prefix_len = 7 if key.startswith("sk-") else 4
    suffix_len = 4
    if len(key) <= prefix_len + suffix_len:
        return f"{key[:2]}...{key[-2:]}"
    return f"{key[:prefix_len]}...{key[-suffix_len:]}"
