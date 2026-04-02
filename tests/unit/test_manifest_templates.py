"""Unit tests for src/manifest_templates.py."""

import src.manifest_templates as mf

DEVICE = "D1"


def test_add_or_update_sets_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    mf.add_or_update_template_entry(DEVICE, "MyTpl.svg", ["Perso"], "\ue9fe")
    entry = mf.get_manifest_entry(DEVICE, "MyTpl.svg")

    assert entry is not None
    assert entry["filename"] == "MyTpl"
    assert entry["syncStatus"] == "pending"


def test_mark_template_deleted_sets_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    mf.add_or_update_template_entry(DEVICE, "MyTpl.svg", ["Perso"], "\ue9fe")
    mf.mark_template_deleted(DEVICE, "MyTpl.svg")
    entry = mf.get_manifest_entry(DEVICE, "MyTpl.svg")

    assert entry is not None
    assert entry["syncStatus"] == "deleted"


def test_mark_synced_transitions_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    mf.add_or_update_template_entry(DEVICE, "A.svg", ["Perso"], "\ue9fe")
    mf.mark_synced(DEVICE)
    entry = mf.get_manifest_entry(DEVICE, "A.svg")

    assert entry is not None
    assert entry["syncStatus"] == "synced"


def test_upsert_orphan_entry_status_orphan(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    mf.upsert_orphan_entry(DEVICE, "Remote.template", ["Grid"], "\ue9fd")
    entry = mf.get_manifest_entry(DEVICE, "Remote.template")

    assert entry is not None
    assert entry["syncStatus"] == "orphan"
    assert entry["categories"] == ["Grid"]


def test_set_sync_status_updates_existing_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    mf.add_or_update_template_entry(DEVICE, "State.svg", ["Perso"], "\ue9fe")
    ok = mf.set_sync_status(DEVICE, "State.svg", "orphan")
    entry = mf.get_manifest_entry(DEVICE, "State.svg")

    assert ok is True
    assert entry is not None
    assert entry["syncStatus"] == "orphan"


def test_set_sync_status_rejects_invalid_status(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    mf.add_or_update_template_entry(DEVICE, "State.svg", ["Perso"], "\ue9fe")
    ok = mf.set_sync_status(DEVICE, "State.svg", "invalid")
    entry = mf.get_manifest_entry(DEVICE, "State.svg")

    assert ok is False
    assert entry is not None
    assert entry["syncStatus"] == "pending"


def test_ensure_manifest_prefers_imported_templates_json_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    device_dir = tmp_path / DEVICE
    (device_dir / "templates").mkdir(parents=True, exist_ok=True)
    (device_dir / "templates" / "Blank.svg").write_text("<svg/>", encoding="utf-8")

    mf.ensure_manifest_from_templates_json(
        DEVICE,
        {
            "templates": [
                {
                    "name": "Blank imported",
                    "filename": "Blank",
                    "iconCode": "\ue9ab",
                    "categories": ["Lines", "Creative"],
                }
            ]
        },
    )

    entry = mf.get_manifest_entry(DEVICE, "Blank")
    assert entry is not None
    assert entry["name"] == "Blank imported"
    assert entry["iconCode"] == "\ue9ab"
    assert entry["categories"] == ["Creative", "Lines"]


def test_ensure_manifest_infers_categories_from_unreferenced_template_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    device_dir = tmp_path / DEVICE
    templates_dir = device_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    (templates_dir / "MyTemplate.template").write_text(
        '{"categories": ["Planners", "Creative"]}',
        encoding="utf-8",
    )

    mf.ensure_manifest_from_templates_json(DEVICE, {"templates": []})

    entry = mf.get_manifest_entry(DEVICE, "MyTemplate")
    assert entry is not None
    assert entry["iconCode"] == "\\ue9fe"
    assert entry["categories"] == ["Creative", "Planners"]


def test_ensure_manifest_excludes_stock_only_templates_without_local_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))

    device_dir = tmp_path / DEVICE
    (device_dir / "templates").mkdir(parents=True, exist_ok=True)

    mf.ensure_manifest_from_templates_json(
        DEVICE,
        {
            "templates": [
                {
                    "name": "Blank",
                    "filename": "Blank",
                    "iconCode": "\\ue9fe",
                    "categories": ["Lines"],
                }
            ]
        },
    )

    assert mf.get_manifest_entry(DEVICE, "Blank") is None
