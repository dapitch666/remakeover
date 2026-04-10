import json
import os
from unittest.mock import patch

import src.templates as tpl
from src.manifest_templates import (
    get_manifest_entry,
    load_manifest,
)


def _set_data_dir(tmp_path):
    os.environ["RM_DATA_DIR"] = str(tmp_path)


def _uuid_for_filename(device_name: str, filename: str) -> str | None:
    stem = os.path.splitext(filename)[0]
    templates = load_manifest(device_name).get("templates", {})
    if not isinstance(templates, dict):
        return None
    for template_uuid, entry in templates.items():
        if isinstance(template_uuid, str) and isinstance(entry, dict) and entry.get("name") == stem:
            return template_uuid
    if len(templates) == 1:
        only_uuid = next(iter(templates.keys()))
        return only_uuid if isinstance(only_uuid, str) else None
    return None


def test_ensure_template_payload_adds_required_fields():
    payload = {"name": "My template", "categories": ["Work"]}
    normalized = tpl.ensure_template_payload(payload)

    assert normalized["name"] == "My template"
    assert normalized["categories"] == ["Work"]
    assert isinstance(normalized["labels"], list)
    assert isinstance(normalized["iconData"], str)
    assert normalized["iconData"]


def test_ensure_remote_template_dirs_creates_xochitl_dir(tmp_path):
    _set_data_dir(tmp_path)

    with patch("src.templates.run_ssh_cmd", return_value=("", "")) as run_cmd:
        ok, _ = tpl.ensure_remote_template_dirs("1.2.3.4", "pw")

    assert ok is True
    run_cmd.assert_called_once()
    cmd = run_cmd.call_args.args[2][0]
    assert "mkdir -p" in cmd


def test_add_template_entry_propagates_json_name_to_manifest_and_metadata(tmp_path):
    _set_data_dir(tmp_path)

    filename = "editor.template"
    tpl.save_json_template(
        "D1",
        filename,
        json.dumps({"name": "Initial Name", "categories": ["Perso"]}),
    )
    tpl.add_template_entry("D1", filename)

    tpl.save_json_template(
        "D1",
        filename,
        json.dumps({"name": "Edited Name", "categories": ["Perso"]}),
    )
    tpl.add_template_entry("D1", filename, previous_filename=filename)

    template_uuid = _uuid_for_filename("D1", filename)
    assert template_uuid is not None

    entry = get_manifest_entry("D1", template_uuid)
    assert entry is not None
    assert entry["name"] == "Edited Name"

    payload = json.loads(tpl.load_json_template("D1", f"{template_uuid}.template"))
    assert payload["name"] == "Edited Name"

    metadata_path = os.path.join(tpl.get_device_templates_dir("D1"), f"{template_uuid}.metadata")
    with open(metadata_path, encoding="utf-8") as f:
        metadata = json.loads(f.read())
    assert metadata["visibleName"] == "Edited Name"


# ---------------------------------------------------------------------------
# get_all_categories / get_all_labels
# ---------------------------------------------------------------------------


def test_get_all_categories_aggregates_across_templates(tmp_path):
    _set_data_dir(tmp_path)
    tpl.save_json_template(
        "D1", "a.template", json.dumps({"name": "A", "categories": ["Lines", "Grids"]})
    )
    tpl.save_json_template(
        "D1", "b.template", json.dumps({"name": "B", "categories": ["Grids", "Perso"]})
    )
    tpl.add_template_entry("D1", "a.template")
    tpl.add_template_entry("D1", "b.template")
    cats = tpl.get_all_categories("D1")
    assert cats == sorted({"Lines", "Grids", "Perso"})


def test_get_all_categories_empty_when_no_templates(tmp_path):
    _set_data_dir(tmp_path)
    assert tpl.get_all_categories("D1") == []


def test_get_all_labels_aggregates_across_templates(tmp_path):
    _set_data_dir(tmp_path)
    tpl.save_json_template("D1", "a.template", json.dumps({"name": "A", "labels": ["x", "y"]}))
    tpl.save_json_template("D1", "b.template", json.dumps({"name": "B", "labels": ["y", "z"]}))
    tpl.add_template_entry("D1", "a.template")
    tpl.add_template_entry("D1", "b.template")
    labels = tpl.get_all_labels("D1")
    assert labels == sorted({"x", "y", "z"})


def test_get_all_labels_empty_when_no_templates(tmp_path):
    _set_data_dir(tmp_path)
    assert tpl.get_all_labels("D1") == []


# ---------------------------------------------------------------------------
# get_template_entry
# ---------------------------------------------------------------------------


def test_get_template_entry_returns_combined_data(tmp_path):
    _set_data_dir(tmp_path)
    tpl.save_json_template(
        "D1",
        "Entry.template",
        json.dumps({"name": "Entry", "categories": ["Work"], "labels": ["l1"]}),
    )
    tpl.add_template_entry("D1", "Entry.template")
    entry = tpl.get_template_entry("D1", "Entry.template")
    assert entry is not None
    assert entry["name"] == "Entry"
    assert "Work" in entry["categories"]
    assert "l1" in entry["labels"]


def test_get_template_entry_returns_none_for_unknown(tmp_path):
    _set_data_dir(tmp_path)
    result = tpl.get_template_entry("D1", "ghost.template")
    assert result is None


# ---------------------------------------------------------------------------
# list_device_templates
# ---------------------------------------------------------------------------


def test_list_device_templates_returns_uuid_filenames(tmp_path):
    _set_data_dir(tmp_path)
    tpl.save_json_template("D1", "named.template", json.dumps({"name": "Named"}))
    tpl.add_template_entry("D1", "named.template")
    files = tpl.list_device_templates("D1")
    assert len(files) == 1
    # After add_template_entry the file is stored as a UUID
    import uuid as _uuid

    stem = os.path.splitext(files[0])[0]
    _uuid.UUID(stem)  # must not raise


# ---------------------------------------------------------------------------
# save / load / delete device template
# ---------------------------------------------------------------------------


def test_delete_device_template_removes_files(tmp_path):
    _set_data_dir(tmp_path)
    tpl.save_json_template("D1", "del.template", json.dumps({"name": "Del"}))
    tpl.add_template_entry("D1", "del.template")
    files_before = tpl.list_device_templates("D1")
    assert len(files_before) == 1
    tpl.delete_device_template("D1", "del.template")
    files_after = tpl.list_device_templates("D1")
    assert len(files_after) == 0


# ---------------------------------------------------------------------------
# remove_template_entry
# ---------------------------------------------------------------------------


def test_remove_template_entry_deletes_manifest_entry(tmp_path):
    _set_data_dir(tmp_path)
    tpl.save_json_template("D1", "rem.template", json.dumps({"name": "ToRemove"}))
    tpl.add_template_entry("D1", "rem.template")
    assert len(load_manifest("D1").get("templates", {})) == 1
    tpl.remove_template_entry("D1", "rem.template")
    assert len(load_manifest("D1").get("templates", {})) == 0
