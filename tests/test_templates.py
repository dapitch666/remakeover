"""Unit tests for src.templates — local helpers, JSON management, and remote helpers."""

import json
import os
from unittest.mock import patch

import pytest

import src.templates as tpl

DEVICE = "TestDevice"
SVG_CONTENT = b"<svg><rect width='100' height='100'/></svg>"
JSON_STOCK = json.dumps(
    {
        "templates": [
            {"name": "Blank", "filename": "Blank", "iconCode": "\ue9fe", "categories": ["Lines"]}
        ]
    }
).encode()
JSON_LOCAL = json.dumps(
    {
        "templates": [
            {"name": "Blank", "filename": "Blank", "iconCode": "\ue9fe", "categories": ["Lines"]},
            {
                "name": "MyColor",
                "filename": "MyColor",
                "iconCode": "\ue9fe",
                "categories": ["Color"],
            },
        ]
    }
).encode()


@pytest.fixture(autouse=True)
def _patch_data_dir(tmp_path, monkeypatch):
    """Redirect get_device_data_dir to tmp_path so no real data/ is touched."""
    monkeypatch.setattr(tpl, "get_device_data_dir", lambda name: str(tmp_path / name))


# ---------------------------------------------------------------------------
# Local file helpers
# ---------------------------------------------------------------------------


class TestLocalFileHelpers:
    def test_get_device_templates_dir_creates_dir(self, tmp_path):
        d = tpl.get_device_templates_dir(DEVICE)
        assert os.path.isdir(d)
        assert d.endswith("templates")

    def test_save_and_load_roundtrip(self):
        path = tpl.save_device_template(DEVICE, SVG_CONTENT, "Red.svg")
        assert os.path.exists(path)
        assert tpl.load_device_template(DEVICE, "Red.svg") == SVG_CONTENT

    def test_list_device_templates_empty(self):
        assert tpl.list_device_templates(DEVICE) == []

    def test_list_device_templates_returns_svgs_only(self):
        tpl.save_device_template(DEVICE, SVG_CONTENT, "A.svg")
        tpl.save_device_template(DEVICE, b"nosvg", "readme.txt")
        result = tpl.list_device_templates(DEVICE)
        assert result == ["A.svg"]
        assert "readme.txt" not in result

    def test_list_device_templates_sorted_by_mtime_desc(self, tmp_path):
        # Create files with known mtimes
        tpl.save_device_template(DEVICE, SVG_CONTENT, "Old.svg")
        tpl.save_device_template(DEVICE, SVG_CONTENT, "New.svg")
        d = tpl.get_device_templates_dir(DEVICE)
        os.utime(os.path.join(d, "Old.svg"), (1000, 1000))
        os.utime(os.path.join(d, "New.svg"), (2000, 2000))
        result = tpl.list_device_templates(DEVICE)
        assert result[0] == "New.svg"
        assert result[1] == "Old.svg"

    def test_delete_device_template_removes_file(self):
        tpl.save_device_template(DEVICE, SVG_CONTENT, "Gone.svg")
        tpl.delete_device_template(DEVICE, "Gone.svg")
        assert tpl.list_device_templates(DEVICE) == []

    def test_delete_device_template_missing_file_is_noop(self):
        tpl.delete_device_template(DEVICE, "nonexistent.svg")  # must not raise

    def test_rename_device_template_success(self):
        tpl.save_device_template(DEVICE, SVG_CONTENT, "Before.svg")
        result = tpl.rename_device_template(DEVICE, "Before.svg", "After.svg")
        assert result is True
        assert "After.svg" in tpl.list_device_templates(DEVICE)
        assert "Before.svg" not in tpl.list_device_templates(DEVICE)

    def test_rename_device_template_missing_source(self):
        assert tpl.rename_device_template(DEVICE, "ghost.svg", "new.svg") is False


# ---------------------------------------------------------------------------
# JSON management
# ---------------------------------------------------------------------------


class TestStem:
    def test_strips_svg(self):
        assert tpl._stem("MyFile.svg") == "MyFile"
        assert tpl._stem("MyFile.SVG") == "MyFile"

    def test_no_extension_unchanged(self):
        assert tpl._stem("MyFile") == "MyFile"

    def test_other_extension_unchanged(self):
        assert tpl._stem("MyFile.png") == "MyFile.png"


class TestJsonHelpers:
    def test_load_templates_json_missing_returns_empty(self):
        data = tpl.load_templates_json(DEVICE)
        assert data == {"templates": []}

    def test_save_and_load_roundtrip(self):
        original = {
            "templates": [{"name": "X", "filename": "X", "iconCode": "\ue9fe", "categories": []}]
        }
        tpl.save_templates_json(DEVICE, original)
        assert tpl.load_templates_json(DEVICE) == original

    def test_add_template_entry_new(self):
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])
        entry = tpl.get_template_entry(DEVICE, "Red.svg")
        assert entry is not None
        assert entry["filename"] == "Red"
        assert entry["name"] == "Red"
        assert entry["categories"] == ["Color"]
        assert entry["iconCode"] == "\ue9fe"

    def test_add_template_entry_custom_icon(self):
        tpl.add_template_entry(DEVICE, "Blue.svg", ["Color"], icon_code="\ue9fd")
        entry = tpl.get_template_entry(DEVICE, "Blue.svg")
        assert entry["iconCode"] == "\ue9fd"

    def test_add_template_entry_replaces_existing(self):
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])
        tpl.add_template_entry(DEVICE, "Red.svg", ["New", "Categories"])
        data = tpl.load_templates_json(DEVICE)
        reds = [t for t in data["templates"] if t["filename"] == "Red"]
        assert len(reds) == 1
        assert reds[0]["categories"] == ["New", "Categories"]

    def test_remove_template_entry(self):
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])
        tpl.add_template_entry(DEVICE, "Blue.svg", ["Color"])
        tpl.remove_template_entry(DEVICE, "Red.svg")
        assert tpl.get_template_entry(DEVICE, "Red.svg") is None
        assert tpl.get_template_entry(DEVICE, "Blue.svg") is not None

    def test_remove_template_entry_missing_is_noop(self):
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])
        tpl.remove_template_entry(DEVICE, "Ghost.svg")  # must not raise or alter others
        assert tpl.get_template_entry(DEVICE, "Red.svg") is not None

    def test_rename_template_entry(self):
        tpl.add_template_entry(DEVICE, "Old.svg", ["Color"])
        tpl.rename_template_entry(DEVICE, "Old.svg", "New.svg")
        assert tpl.get_template_entry(DEVICE, "Old.svg") is None
        entry = tpl.get_template_entry(DEVICE, "New.svg")
        assert entry is not None
        assert entry["filename"] == "New"
        assert entry["name"] == "New"

    def test_rename_template_entry_missing_is_noop(self):
        tpl.add_template_entry(DEVICE, "A.svg", ["X"])
        tpl.rename_template_entry(DEVICE, "Ghost.svg", "New.svg")  # must not raise
        assert tpl.get_template_entry(DEVICE, "A.svg") is not None

    def test_update_template_categories(self):
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])
        tpl.update_template_categories(DEVICE, "Red.svg", ["Color", "Perso"])
        assert tpl.get_template_entry(DEVICE, "Red.svg")["categories"] == ["Color", "Perso"]

    def test_update_template_categories_missing_is_noop(self):
        tpl.update_template_categories(DEVICE, "Ghost.svg", ["X"])  # must not raise

    def test_get_all_categories_distinct_sorted(self):
        tpl.add_template_entry(DEVICE, "A.svg", ["Zebra", "Color"])
        tpl.add_template_entry(DEVICE, "B.svg", ["Color", "Lines"])
        cats = tpl.get_all_categories(DEVICE)
        assert cats == ["Color", "Lines", "Zebra"]

    def test_get_all_categories_empty(self):
        assert tpl.get_all_categories(DEVICE) == []

    def test_get_template_entry_not_found(self):
        assert tpl.get_template_entry(DEVICE, "Ghost.svg") is None

    def test_add_entry_accepts_stem_without_extension(self):
        tpl.add_template_entry(DEVICE, "Plain", ["Lines"])
        entry = tpl.get_template_entry(DEVICE, "Plain")
        assert entry is not None
        assert entry["filename"] == "Plain"


# ---------------------------------------------------------------------------
# Remote helpers
# ---------------------------------------------------------------------------


class TestCompareAndBackupTemplatesJson:
    def test_identical_returns_identical(self, tmp_path):
        # Write the same content locally and pretend remote returns it too
        tpl_json_path = os.path.join(str(tmp_path / DEVICE), "templates.json")
        os.makedirs(os.path.dirname(tpl_json_path), exist_ok=True)
        with open(tpl_json_path, "wb") as f:
            f.write(JSON_STOCK)

        with patch("src.templates.download_file_ssh", return_value=JSON_STOCK):
            ok, msg = tpl.compare_and_backup_templates_json("1.2.3.4", "pw", DEVICE)

        assert ok is True
        assert msg == "identical"

    def test_different_backups_and_uploads(self, tmp_path):
        tpl_json_path = os.path.join(str(tmp_path / DEVICE), "templates.json")
        os.makedirs(os.path.dirname(tpl_json_path), exist_ok=True)
        with open(tpl_json_path, "wb") as f:
            f.write(JSON_LOCAL)

        with (
            patch("src.templates.download_file_ssh", return_value=JSON_STOCK),
            patch("src.templates.upload_file_ssh", return_value=(True, "ok")) as mock_upload,
        ):
            ok, msg = tpl.compare_and_backup_templates_json("1.2.3.4", "pw", DEVICE)

        assert ok is True
        assert msg == "uploaded"
        backup_path = os.path.join(str(tmp_path / DEVICE), "templates.backup.json")
        assert os.path.exists(backup_path)
        with open(backup_path, "rb") as f:
            assert f.read() == JSON_STOCK
        mock_upload.assert_called_once()

    def test_no_local_file(self):
        with patch("src.templates.download_file_ssh", return_value=JSON_STOCK):
            ok, msg = tpl.compare_and_backup_templates_json("1.2.3.4", "pw", DEVICE)
        assert ok is False
        assert msg == "no_local"

    def test_download_failure(self):
        with patch("src.templates.download_file_ssh", side_effect=Exception("timeout")):
            ok, msg = tpl.compare_and_backup_templates_json("1.2.3.4", "pw", DEVICE)
        assert ok is False
        assert msg.startswith("download_failed")

    def test_upload_failure_returns_upload_failed(self, tmp_path):
        tpl_json_path = os.path.join(str(tmp_path / DEVICE), "templates.json")
        os.makedirs(os.path.dirname(tpl_json_path), exist_ok=True)
        with open(tpl_json_path, "wb") as f:
            f.write(JSON_LOCAL)

        with (
            patch("src.templates.download_file_ssh", return_value=JSON_STOCK),
            patch("src.templates.upload_file_ssh", return_value=(False, "disk full")),
        ):
            ok, msg = tpl.compare_and_backup_templates_json("1.2.3.4", "pw", DEVICE)

        assert ok is False
        assert "upload_failed" in msg


class TestUploadTemplateToTablet:
    def _setup_svg(self, tmp_path):
        tpl.save_device_template(DEVICE, SVG_CONTENT, "Red.svg")
        # write a templates.json too so the json push path is exercised
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])

    def test_happy_path(self, tmp_path):
        self._setup_svg(tmp_path)
        with (
            patch("src.templates.upload_file_ssh", return_value=(True, "ok")) as mock_up,
            patch("src.templates.run_ssh_cmd") as mock_cmd,
        ):
            ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")

        assert ok is True
        assert msg == "ok"
        # First call: SVG upload; second call: templates.json push
        assert mock_up.call_count == 2
        mock_cmd.assert_called_once()

    def test_svg_upload_failure(self, tmp_path):
        self._setup_svg(tmp_path)
        with patch("src.templates.upload_file_ssh", return_value=(False, "denied")):
            ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is False
        assert "upload_svg_failed" in msg

    def test_symlink_failure(self, tmp_path):
        self._setup_svg(tmp_path)
        with (
            patch("src.templates.upload_file_ssh", return_value=(True, "ok")),
            patch("src.templates.run_ssh_cmd", side_effect=Exception("bash error")),
        ):
            ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is False
        assert "symlink_failed" in msg

    def test_json_upload_failure(self, tmp_path):
        self._setup_svg(tmp_path)
        # First call (SVG) succeeds, second call (json) fails
        with (
            patch("src.templates.upload_file_ssh", side_effect=[(True, "ok"), (False, "error")]),
            patch("src.templates.run_ssh_cmd"),
        ):
            ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is False
        assert "upload_json_failed" in msg

    def test_missing_local_svg(self):
        with patch("src.templates.upload_file_ssh"), patch("src.templates.run_ssh_cmd"):
            ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", DEVICE, "Ghost.svg")
        assert ok is False
        assert "read_local_failed" in msg

    def test_no_local_json_skips_json_push(self, tmp_path):
        """If templates.json doesn't exist, only the SVG upload and symlink are done."""
        tpl.save_device_template(DEVICE, SVG_CONTENT, "Red.svg")
        # no templates.json written
        with (
            patch("src.templates.upload_file_ssh", return_value=(True, "ok")) as mock_up,
            patch("src.templates.run_ssh_cmd"),
        ):
            ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is True
        assert mock_up.call_count == 1  # only SVG, no json push


class TestRemoveTemplateFromTablet:
    def _setup(self, tmp_path):
        tpl.save_device_template(DEVICE, SVG_CONTENT, "Red.svg")
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])

    def test_happy_path(self, tmp_path):
        self._setup(tmp_path)
        with (
            patch("src.templates.run_ssh_cmd") as mock_cmd,
            patch("src.templates.upload_file_ssh", return_value=(True, "ok")) as mock_up,
        ):
            ok, msg = tpl.remove_template_from_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is True
        assert msg == "ok"
        mock_cmd.assert_called_once()
        mock_up.assert_called_once()

    def test_remove_failure(self, tmp_path):
        self._setup(tmp_path)
        with patch("src.templates.run_ssh_cmd", side_effect=Exception("permission denied")):
            ok, msg = tpl.remove_template_from_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is False
        assert "remove_failed" in msg

    def test_json_upload_failure(self, tmp_path):
        self._setup(tmp_path)
        with (
            patch("src.templates.run_ssh_cmd"),
            patch("src.templates.upload_file_ssh", return_value=(False, "io error")),
        ):
            ok, msg = tpl.remove_template_from_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is False
        assert "upload_json_failed" in msg

    def test_no_local_json_skips_json_push(self, tmp_path):
        """If templates.json doesn't exist, only the rm command is issued."""
        tpl.save_device_template(DEVICE, SVG_CONTENT, "Red.svg")
        with (
            patch("src.templates.run_ssh_cmd") as mock_cmd,
            patch("src.templates.upload_file_ssh") as mock_up,
        ):
            ok, msg = tpl.remove_template_from_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is True
        mock_cmd.assert_called_once()
        mock_up.assert_not_called()
