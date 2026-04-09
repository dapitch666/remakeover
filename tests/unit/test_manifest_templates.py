"""Unit tests for the simplified UUID-keyed template manifest."""

import src.manifest_templates as mf

DEVICE = "D1"


def test_compute_template_sha256_is_canonical():
    payload_a = {"b": 2, "a": 1}
    payload_b = {"a": 1, "b": 2}

    assert mf.compute_template_sha256(payload_a) == mf.compute_template_sha256(payload_b)


def test_upsert_and_get_manifest_entry_by_uuid_only(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    template_uuid = "11111111-1111-4111-8111-111111111111"
    mf.upsert_manifest_template(
        DEVICE,
        template_uuid,
        name="MyTpl",
        created_at="2026-04-04T10:00:00Z",
        sha256="abc123",
    )

    by_uuid = mf.get_manifest_entry(DEVICE, template_uuid)

    assert by_uuid is not None
    assert by_uuid["uuid"] == template_uuid
    assert by_uuid["name"] == "MyTpl"
    assert by_uuid["sha256"] == "abc123"


def test_upsert_keeps_created_at_when_entry_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    template_uuid = "22222222-2222-4222-8222-222222222222"
    mf.upsert_manifest_template(
        DEVICE,
        template_uuid,
        name="Tpl",
        created_at="2026-04-04T10:00:00Z",
        sha256="old",
    )
    mf.upsert_manifest_template(
        DEVICE,
        template_uuid,
        name="Tpl",
        created_at="2099-01-01T00:00:00Z",
        sha256="new",
    )

    entry = mf.get_manifest_entry(DEVICE, template_uuid)
    assert entry is not None
    assert entry["created_at"] == "2026-04-04T10:00:00Z"
    assert entry["sha256"] == "new"


def test_delete_manifest_template(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    template_uuid = "33333333-3333-4333-8333-333333333333"
    mf.upsert_manifest_template(
        DEVICE,
        template_uuid,
        name="ToDelete",
        created_at="2026-04-04T10:00:00Z",
        sha256="deadbeef",
    )

    assert mf.delete_manifest_template(DEVICE, template_uuid) is True
    assert mf.get_manifest_entry(DEVICE, template_uuid) is None


def test_iso_from_epoch_ms_returns_utc_iso():
    assert mf.iso_from_epoch_ms("1712150515000") == "2024-04-03T13:21:55Z"
