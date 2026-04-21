import json
import os
import uuid as _uuid_mod

import src.templates as tpl
from src.manifest_templates import (
    get_manifest_entry,
    load_manifest,
    save_manifest,
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
# get_template_entry_by_uuid — orientation field
# ---------------------------------------------------------------------------


def test_get_template_entry_by_uuid_returns_landscape_orientation(tmp_path):
    _set_data_dir(tmp_path)
    tpl.save_json_template(
        "D1", "ls.template", json.dumps({"name": "Landscape", "orientation": "landscape"})
    )
    tpl.add_template_entry("D1", "ls.template")
    template_uuid = next(iter(load_manifest("D1").get("templates", {})))
    entry = tpl.get_template_entry_by_uuid("D1", template_uuid)
    assert entry is not None
    assert entry["orientation"] == "landscape"


def test_get_template_entry_by_uuid_returns_portrait_orientation(tmp_path):
    _set_data_dir(tmp_path)
    tpl.save_json_template(
        "D1", "pt.template", json.dumps({"name": "Portrait", "orientation": "portrait"})
    )
    tpl.add_template_entry("D1", "pt.template")
    template_uuid = next(iter(load_manifest("D1").get("templates", {})))
    entry = tpl.get_template_entry_by_uuid("D1", template_uuid)
    assert entry is not None
    assert entry["orientation"] == "portrait"


def test_get_template_entry_by_uuid_defaults_orientation_when_missing(tmp_path):
    _set_data_dir(tmp_path)
    tpl.save_json_template("D1", "no_orient.template", json.dumps({"name": "No Orientation"}))
    tpl.add_template_entry("D1", "no_orient.template")
    template_uuid = next(iter(load_manifest("D1").get("templates", {})))
    entry = tpl.get_template_entry_by_uuid("D1", template_uuid)
    assert entry is not None
    assert entry["orientation"] == "portrait"


def test_get_template_entry_by_uuid_rejects_invalid_orientation(tmp_path):
    _set_data_dir(tmp_path)
    tpl.save_json_template(
        "D1", "bad_orient.template", json.dumps({"name": "Bad", "orientation": "sideways"})
    )
    tpl.add_template_entry("D1", "bad_orient.template")
    template_uuid = next(iter(load_manifest("D1").get("templates", {})))
    entry = tpl.get_template_entry_by_uuid("D1", template_uuid)
    assert entry is not None
    assert entry["orientation"] == "portrait"


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


# ---------------------------------------------------------------------------
# refresh_local_manifest
# ---------------------------------------------------------------------------


class TestRefreshLocalManifest:
    def test_non_uuid_file_minted_to_uuid_and_renamed(self, tmp_path):
        """A plain-name .template file is assigned a fresh UUID, renamed, and manifest entry created."""
        _set_data_dir(tmp_path)
        tdir = tpl.get_device_templates_dir("D1")

        with open(os.path.join(tdir, "my_template.template"), "w", encoding="utf-8") as f:
            json.dump({"name": "My Template"}, f)

        tpl.refresh_local_manifest("D1")

        templates = load_manifest("D1").get("templates", {})
        assert len(templates) == 1
        template_uuid = next(iter(templates))
        _uuid_mod.UUID(template_uuid)  # must be a valid UUID
        assert templates[template_uuid]["name"] == "my_template"  # stem wins over payload name
        assert os.path.exists(os.path.join(tdir, f"{template_uuid}.template"))
        assert not os.path.exists(os.path.join(tdir, "my_template.template"))

    def test_non_uuid_file_reuses_existing_uuid_from_manifest(self, tmp_path):
        """A plain-name file whose stem matches an existing manifest entry reuses the known UUID."""
        _set_data_dir(tmp_path)
        tdir = tpl.get_device_templates_dir("D1")
        fixed_uuid = str(_uuid_mod.uuid4())

        save_manifest("D1", {"templates": {fixed_uuid: {"name": "my_template", "sha256": "old"}}})
        with open(os.path.join(tdir, "my_template.template"), "w", encoding="utf-8") as f:
            json.dump({"name": "my_template"}, f)

        tpl.refresh_local_manifest("D1")

        templates = load_manifest("D1").get("templates", {})
        assert fixed_uuid in templates, "Existing UUID must be reused, not minted fresh"
        assert len(templates) == 1

    def test_metadata_visible_name_takes_priority_over_payload_name(self, tmp_path):
        """metadata.visibleName wins over the JSON payload name and overwrites the .template file."""
        _set_data_dir(tmp_path)
        tdir = tpl.get_device_templates_dir("D1")
        fixed_uuid = str(_uuid_mod.uuid4())

        tpl_path = os.path.join(tdir, f"{fixed_uuid}.template")
        meta_path = os.path.join(tdir, f"{fixed_uuid}.metadata")
        with open(tpl_path, "w", encoding="utf-8") as f:
            json.dump({"name": "Old Payload Name"}, f)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"visibleName": "Metadata Name", "type": "TemplateType"}, f)

        tpl.refresh_local_manifest("D1")

        templates = load_manifest("D1").get("templates", {})
        assert templates[fixed_uuid]["name"] == "Metadata Name"
        with open(tpl_path, encoding="utf-8") as f:
            rewritten = json.loads(f.read())
        assert rewritten["name"] == "Metadata Name"

    def test_manifest_name_wins_when_no_metadata(self, tmp_path):
        """Existing manifest entry name wins over payload name when no metadata file is present."""
        _set_data_dir(tmp_path)
        tdir = tpl.get_device_templates_dir("D1")
        fixed_uuid = str(_uuid_mod.uuid4())

        save_manifest(
            "D1",
            {
                "templates": {
                    fixed_uuid: {
                        "name": "Manifest Name",
                        "sha256": "old",
                        "created_at": "2024-01-01T00:00:00Z",
                    }
                }
            },
        )
        tpl_path = os.path.join(tdir, f"{fixed_uuid}.template")
        with open(tpl_path, "w", encoding="utf-8") as f:
            json.dump({"name": "Payload Name"}, f)

        tpl.refresh_local_manifest("D1")

        templates = load_manifest("D1").get("templates", {})
        assert templates[fixed_uuid]["name"] == "Manifest Name"
        with open(tpl_path, encoding="utf-8") as f:
            rewritten = json.loads(f.read())
        assert rewritten["name"] == "Manifest Name"

    def test_created_at_preserved_and_sha256_updated(self, tmp_path):
        """created_at from existing manifest entry is preserved; sha256 is recomputed."""
        _set_data_dir(tmp_path)
        tdir = tpl.get_device_templates_dir("D1")
        fixed_uuid = str(_uuid_mod.uuid4())
        original_created_at = "2023-06-15T10:00:00Z"

        save_manifest(
            "D1",
            {
                "templates": {
                    fixed_uuid: {
                        "name": "Stable",
                        "sha256": "stale_hash",
                        "created_at": original_created_at,
                    }
                }
            },
        )
        with open(os.path.join(tdir, f"{fixed_uuid}.template"), "w", encoding="utf-8") as f:
            json.dump({"name": "Stable"}, f)

        tpl.refresh_local_manifest("D1")

        entry = load_manifest("D1")["templates"][fixed_uuid]
        assert entry["created_at"] == original_created_at
        assert entry["sha256"] != "stale_hash"
        assert entry["sha256"]

    def test_orphan_manifest_entries_removed(self, tmp_path):
        """Manifest entries with no corresponding .template file on disk are pruned."""
        _set_data_dir(tmp_path)
        tdir = tpl.get_device_templates_dir("D1")
        real_uuid = str(_uuid_mod.uuid4())
        ghost_uuid = str(_uuid_mod.uuid4())

        save_manifest(
            "D1",
            {
                "templates": {
                    real_uuid: {"name": "Real", "sha256": "x"},
                    ghost_uuid: {"name": "Ghost", "sha256": "y"},
                }
            },
        )
        with open(os.path.join(tdir, f"{real_uuid}.template"), "w", encoding="utf-8") as f:
            json.dump({"name": "Real"}, f)

        tpl.refresh_local_manifest("D1")

        templates = load_manifest("D1").get("templates", {})
        assert real_uuid in templates
        assert ghost_uuid not in templates, "Orphan manifest entry must be removed"
