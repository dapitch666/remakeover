import json
import os
from unittest.mock import patch

import src.template_sync as sync
import src.templates as tpl
from src.manifest_templates import (
    compute_template_sha256_from_template_content,
    get_manifest_entry,
    load_manifest,
    upsert_manifest_template,
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


def test_ensure_template_payload_for_rmethods_adds_required_fields():
    payload = {"name": "My template", "categories": ["Work"]}
    normalized = tpl.ensure_template_payload_for_rmethods(payload)

    assert normalized["name"] == "My template"
    assert normalized["categories"] == ["Work"]
    assert isinstance(normalized["labels"], list)
    assert isinstance(normalized["iconData"], str)
    assert normalized["iconData"]


def test_list_remote_custom_templates_returns_uuid_template_names():
    with patch("src.templates._list_remote_custom_templates", return_value=(True, ["u1", "u2"])):
        ok, payload = tpl.list_remote_custom_templates("1.2.3.4", "pw")

    assert ok is True
    assert payload == {"u1", "u2"}


def test_ensure_remote_template_dirs_creates_xochitl_dir(tmp_path):
    _set_data_dir(tmp_path)

    with patch("src.templates.run_ssh_cmd", return_value=("", "")) as run_cmd:
        ok, _ = tpl.ensure_remote_template_dirs("1.2.3.4", "pw")

    assert ok is True
    run_cmd.assert_called_once()
    cmd = run_cmd.call_args.args[2][0]
    assert "mkdir -p" in cmd


def test_fetch_and_init_templates_imports_remote_rmethods_templates(tmp_path):
    _set_data_dir(tmp_path)

    remote_uuid = "11111111-2222-4333-8444-555555555555"
    metadata = {
        "type": "TemplateType",
        "visibleName": "My Remote Template",
    }
    template_payload = {
        "name": "Remote Name",
        "categories": ["Work"],
    }

    def _download(_ip, _pw, path):
        if path.endswith(".metadata"):
            return json.dumps(metadata).encode("utf-8"), ""
        if path.endswith(".template"):
            return json.dumps(template_payload).encode("utf-8"), ""
        return None, "missing"

    with (
        patch("src.templates._list_remote_custom_templates", return_value=(True, [remote_uuid])),
        patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
        patch(
            "src.template_sync._push_remote_manifest", return_value=(True, "ok")
        ) as push_manifest,
    ):
        ok, msg = sync.fetch_and_init_templates("1.2.3.4", "pw", "D1")

    assert ok is True
    assert "1 template(s) imported" in msg
    push_manifest.assert_called_once()

    local_files = tpl.list_json_templates("D1")
    assert len(local_files) == 1
    content = tpl.load_json_template("D1", local_files[0])
    parsed = json.loads(content)
    assert parsed["name"] == "My Remote Template"
    assert parsed["labels"] == []
    assert isinstance(parsed["iconData"], str)

    template_uuid = _uuid_for_filename("D1", local_files[0])
    assert template_uuid is not None
    entry = get_manifest_entry("D1", template_uuid)
    assert entry is not None
    assert entry["uuid"] == remote_uuid
    assert entry["sha256"]


def test_upload_template_to_tablet_writes_uuid_triplet_and_sets_remote_uuid(tmp_path):
    _set_data_dir(tmp_path)

    filename = "my_template.template"
    tpl.save_json_template(
        "D1",
        filename,
        json.dumps({"name": "Visible Name", "categories": ["Perso"]}),
    )
    tpl.add_template_entry("D1", filename, ["Perso"], "\ue9fe")

    uploaded_paths = []

    def _upload(_ip, _pw, _content, remote_path):
        uploaded_paths.append(remote_path)
        return True, "ok"

    with (
        patch("src.templates.upload_file_ssh", side_effect=_upload),
        patch("src.templates.run_ssh_cmd", return_value=("", "")),
    ):
        ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", "D1", filename)

    assert ok is True
    assert msg == "ok"
    assert any(path.endswith(".template") for path in uploaded_paths)
    assert any(path.endswith(".metadata") for path in uploaded_paths)
    assert any(path.endswith(".content") for path in uploaded_paths)
    assert any(path.endswith("/.manifest.json") for path in uploaded_paths)

    template_uuid = _uuid_for_filename("D1", filename)
    assert template_uuid is not None
    entry = get_manifest_entry("D1", template_uuid)
    assert entry is not None
    assert any(path.endswith(f"/{entry['uuid']}.template") for path in uploaded_paths)


def test_rename_device_template_updates_json_metadata_and_manifest(tmp_path):
    _set_data_dir(tmp_path)

    filename = "original.template"
    tpl.save_json_template(
        "D1",
        filename,
        json.dumps({"name": "Original", "categories": ["Perso"]}),
    )
    tpl.add_template_entry("D1", filename, ["Perso"], "\ue9fe")

    template_uuid = _uuid_for_filename("D1", filename)
    assert template_uuid is not None

    assert tpl.rename_device_template("D1", filename, "Renamed.template") is True

    entry = get_manifest_entry("D1", template_uuid)
    assert entry is not None
    assert entry["name"] == "Renamed"

    payload = json.loads(tpl.load_json_template("D1", f"{template_uuid}.template"))
    assert payload["name"] == "Renamed"

    metadata_path = os.path.join(tpl.get_device_templates_dir("D1"), f"{template_uuid}.metadata")
    with open(metadata_path, encoding="utf-8") as f:
        metadata = json.loads(f.read())
    assert metadata["visibleName"] == "Renamed"


def test_add_template_entry_propagates_json_name_to_manifest_and_metadata(tmp_path):
    _set_data_dir(tmp_path)

    filename = "editor.template"
    tpl.save_json_template(
        "D1",
        filename,
        json.dumps({"name": "Initial Name", "categories": ["Perso"]}),
    )
    tpl.add_template_entry("D1", filename, ["Perso"], "\ue9fe")

    tpl.save_json_template(
        "D1",
        filename,
        json.dumps({"name": "Edited Name", "categories": ["Perso"]}),
    )
    tpl.add_template_entry("D1", filename, ["Perso"], "\ue9fe", previous_filename=filename)

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


def test_delete_template_from_tablet_removes_uuid_triplet(tmp_path):
    _set_data_dir(tmp_path)

    filename = "my_template.template"
    remote_uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    payload = json.dumps({"name": "To delete"})
    tpl.save_json_template("D1", filename, payload)
    upsert_manifest_template(
        "D1",
        remote_uuid,
        name="my_template",
        created_at="2026-04-04T10:00:00Z",
        sha256=compute_template_sha256_from_template_content(payload) or "",
    )

    executed = []

    def _run(_ip, _pw, cmds):
        executed.extend(cmds)
        return "", ""

    with patch("src.templates.run_ssh_cmd", side_effect=_run):
        ok, msg = tpl.delete_template_from_tablet("1.2.3.4", "pw", "D1", filename)

    assert ok is True
    assert msg == "ok"
    assert any(f"{remote_uuid}.template" in cmd for cmd in executed)
    assert any(f"{remote_uuid}.metadata" in cmd for cmd in executed)
    assert any(f"{remote_uuid}.content" in cmd for cmd in executed)
