"""Unit tests cho các hàm lưu trữ tích hợp LLM trong Store."""
from __future__ import annotations

from chakra_rag.core.security import encrypt_integration_key
from chakra_rag.storage.store import Store


def test_create_and_list_integrations(tmp_path):
    store = Store(tmp_path / "store.db", embed_dim=4)
    assert store.count_integrations() == 0

    enc = encrypt_integration_key("sk-test-key", "my-kek")
    item = store.create_integration(
        name="OpenAI Test",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        provider="openai",
        encrypted_api_key=enc.encrypted_api_key,
        encrypted_dek=enc.encrypted_dek,
        is_active=False,
    )
    # Vì là bản ghi đầu tiên, tự động kích hoạt
    assert item["name"] == "OpenAI Test"
    assert item["is_active"] == 1
    assert store.count_integrations() == 1

    # Tạo bản ghi thứ hai với is_active=True
    enc2 = encrypt_integration_key("sk-key-2", "my-kek")
    item2 = store.create_integration(
        name="DeepSeek Test",
        model="deepseek-v4-flash",
        base_url="https://api.vilao.ai/v1",
        provider="openai",
        encrypted_api_key=enc2.encrypted_api_key,
        encrypted_dek=enc2.encrypted_dek,
        is_active=True,
    )
    assert item2["is_active"] == 1

    # Bản ghi đầu phải trở thành inactive (0)
    first_updated = store.get_integration(item["id"])
    assert first_updated is not None
    assert first_updated["is_active"] == 0

    active = store.get_active_integration()
    assert active is not None
    assert active["id"] == item2["id"]


def test_update_and_delete_integration(tmp_path):
    store = Store(tmp_path / "store.db", embed_dim=4)
    item = store.create_integration(
        name="Model A",
        model="gpt-3.5-turbo",
        is_active=True,
    )
    updated = store.update_integration(
        item["id"],
        name="Model A Renamed",
        model="gpt-4o",
    )
    assert updated is not None
    assert updated["name"] == "Model A Renamed"
    assert updated["model"] == "gpt-4o"

    # Tạo thêm item B
    item_b = store.create_integration(name="Model B", model="model-b", is_active=False)
    # Xóa item active A -> fallback tự động sang item B
    assert store.delete_integration(item["id"]) is True
    active = store.get_active_integration()
    assert active is not None
    assert active["id"] == item_b["id"]
    assert active["is_active"] == 1
