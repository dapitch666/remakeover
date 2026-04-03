import json
import os
from unittest.mock import patch

import src.templates as tpl
from src.manifest_templates import (
    compute_template_sha256_from_template_content,
    get_manifest_entry,
    upsert_manifest_template,
)


def _set_data_dir(tmp_path):
    os.environ["RM_DATA_DIR"] = str(tmp_path)


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
    assert payload == {"u1.template", "u2.template"}


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
        patch("src.templates.download_file_ssh", side_effect=_download),
    ):
        ok, msg = tpl.fetch_and_init_templates("1.2.3.4", "pw", "D1")

    assert ok is True
    assert "1 template(s) imported" in msg

    local_files = tpl.list_json_templates("D1")
    assert len(local_files) == 1
    content = tpl.load_json_template("D1", local_files[0])
    parsed = json.loads(content)
    assert parsed["name"] == "Remote Name"
    assert parsed["labels"] == []
    assert isinstance(parsed["iconData"], str)

    entry = get_manifest_entry("D1", local_files[0])
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

    entry = get_manifest_entry("D1", filename)
    assert entry is not None
    assert any(path.endswith(f"/{entry['uuid']}.template") for path in uploaded_paths)


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
