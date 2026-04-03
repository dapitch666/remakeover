"""Unit tests for src/templates.py — local helpers, JSON management, and remote helpers."""

import json
import os
from unittest.mock import patch

import pytest

import src.templates as tpl
from src import manifest_templates as mf

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
    monkeypatch.setattr(mf, "get_device_data_dir", lambda name: str(tmp_path / name))
    yield
    # Clear the st.cache_data cache so cached results from one test don't
    # leak into the next (all tests share the same device name "TestDevice").
    tpl.load_templates_json.clear()


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


class TestTemplateContentParsing:
    def test_extract_categories_from_template_content(self):
        categories = tpl.extract_categories_from_template_content(
            b'{"categories": ["Lines", "Perso"], "orientation": "portrait"}'
        )
        assert categories == ["Lines", "Perso"]

    def test_extract_categories_from_template_content_missing_categories(self):
        categories = tpl.extract_categories_from_template_content(
            b'{"orientation": "portrait", "items": []}'
        )
        assert categories == []

    def test_extract_categories_from_template_content_invalid_json(self):
        assert tpl.extract_categories_from_template_content(b"not-json") is None

    def test_extract_categories_from_template_content_rejects_non_list(self):
        assert tpl.extract_categories_from_template_content(b'{"categories": "Lines"}') is None


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
        assert reds[0]["categories"] == ["Categories", "New"]

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

    def test_add_template_entry_sorts_categories(self):
        """Categories passed in any order are stored sorted alphabetically."""
        tpl.add_template_entry(DEVICE, "Red.svg", ["Zebra", "Color", "Lines"])
        assert tpl.get_template_entry(DEVICE, "Red.svg")["categories"] == [
            "Color",
            "Lines",
            "Zebra",
        ]

    def test_update_template_categories(self):
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])
        tpl.update_template_categories(DEVICE, "Red.svg", ["Color", "Perso"])
        assert tpl.get_template_entry(DEVICE, "Red.svg")["categories"] == ["Color", "Perso"]

    def test_update_template_categories_sorts_alphabetically(self):
        """update_template_categories stores categories sorted alphabetically."""
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])
        tpl.update_template_categories(DEVICE, "Red.svg", ["Zebra", "Lines", "Color"])
        assert tpl.get_template_entry(DEVICE, "Red.svg")["categories"] == [
            "Color",
            "Lines",
            "Zebra",
        ]

    def test_update_template_categories_missing_is_noop(self):
        tpl.update_template_categories(DEVICE, "Ghost.svg", ["X"])  # must not raise

    def test_update_template_icon_code_updates_entry(self):
        """update_template_icon_code persists the new icon code in templates.json."""
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])
        tpl.update_template_icon_code(DEVICE, "Red.svg", "\ue961")
        assert tpl.get_template_entry(DEVICE, "Red.svg")["iconCode"] == "\ue961"

    def test_update_template_icon_code_missing_is_noop(self):
        """update_template_icon_code on a non-existent entry must not raise or alter others."""
        tpl.add_template_entry(DEVICE, "Red.svg", ["Color"])
        tpl.update_template_icon_code(DEVICE, "Ghost.svg", "\ue961")  # must not raise
        assert tpl.get_template_entry(DEVICE, "Red.svg")["iconCode"] == "\ue9fe"  # unchanged

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

    def test_add_template_entry_sorts_custom_alphabetically(self, tmp_path):
        """Custom templates are sorted alphabetically; re-saving keeps the order stable."""
        tpl.add_template_entry(DEVICE, "Zebra.svg", ["Lines"])
        tpl.add_template_entry(DEVICE, "Apple.svg", ["Lines"])
        tpl.add_template_entry(DEVICE, "Mango.svg", ["Lines"])
        data = tpl.load_templates_json(DEVICE)
        names = [t["filename"] for t in data["templates"]]
        assert names == ["Apple", "Mango", "Zebra"]

    def test_add_template_entry_resave_is_idempotent(self, tmp_path):
        """Re-saving an existing custom template produces the same JSON hash (not dirty)."""
        import hashlib

        tpl.add_template_entry(DEVICE, "Alpha.svg", ["Lines"])
        tpl.add_template_entry(DEVICE, "Beta.svg", ["Lines"])
        json_path = tpl.get_device_templates_json_path(DEVICE)
        with open(json_path, "rb") as f:
            hash_before = hashlib.md5(f.read()).hexdigest()
        # Re-save Beta with the same categories
        tpl.add_template_entry(DEVICE, "Beta.svg", ["Lines"])
        with open(json_path, "rb") as f:
            hash_after = hashlib.md5(f.read()).hexdigest()
        assert hash_before == hash_after

    def test_add_template_entry_stock_templates_keep_order(self, tmp_path):
        """Stock templates (in backup) come first in their original order; custom sorted after."""
        # Write a backup with two stock templates in a specific order
        backup_path = tpl.get_device_templates_backup_path(DEVICE)
        import json as _json

        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        with open(backup_path, "w", encoding="utf-8") as f:
            _json.dump(
                {
                    "templates": [
                        {
                            "name": "StockZ",
                            "filename": "StockZ",
                            "iconCode": "\ue9fe",
                            "categories": [],
                        },
                        {
                            "name": "StockA",
                            "filename": "StockA",
                            "iconCode": "\ue9fe",
                            "categories": [],
                        },
                    ]
                },
                f,
            )
        # Seed templates.json with the stock entries
        tpl.save_templates_json(
            DEVICE,
            {
                "templates": [
                    {
                        "name": "StockZ",
                        "filename": "StockZ",
                        "iconCode": "\ue9fe",
                        "categories": [],
                    },
                    {
                        "name": "StockA",
                        "filename": "StockA",
                        "iconCode": "\ue9fe",
                        "categories": [],
                    },
                ]
            },
        )
        # Add two custom templates
        tpl.add_template_entry(DEVICE, "CustomZ.svg", ["Lines"])
        tpl.add_template_entry(DEVICE, "CustomA.svg", ["Lines"])
        data = tpl.load_templates_json(DEVICE)
        names = [t["filename"] for t in data["templates"]]
        # Stock first in original order, then custom sorted
        assert names == ["StockZ", "StockA", "CustomA", "CustomZ"]

    def test_add_template_entry_rejects_stock_stem_collision(self, tmp_path):
        backup_path = tpl.get_device_templates_backup_path(DEVICE)
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "templates": [
                        {
                            "name": "Blank",
                            "filename": "Blank",
                            "iconCode": "\\ue9fe",
                            "categories": [],
                        }
                    ]
                },
                f,
            )

        with pytest.raises(tpl.StockTemplateNameConflictError):
            tpl.add_template_entry(DEVICE, "Blank.svg", ["Lines"])

    def test_add_template_entry_allows_stock_stem_when_same_previous_filename(self, tmp_path):
        backup_path = tpl.get_device_templates_backup_path(DEVICE)
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "templates": [
                        {
                            "name": "Blank",
                            "filename": "Blank",
                            "iconCode": "\\ue9fe",
                            "categories": [],
                        }
                    ]
                },
                f,
            )

        tpl.save_templates_json(
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

        tpl.add_template_entry(
            DEVICE,
            "Blank.template",
            ["Grid"],
            icon_code="\ue960",
            previous_filename="Blank.template",
        )

        data = tpl.load_templates_json(DEVICE)
        assert len(data["templates"]) == 1
        assert data["templates"][0]["filename"] == "Blank"
        assert data["templates"][0]["categories"] == ["Grid"]
        assert data["templates"][0]["iconCode"] == "\ue960"

    def test_rename_template_entry_rejects_stock_stem_collision(self, tmp_path):
        backup_path = tpl.get_device_templates_backup_path(DEVICE)
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "templates": [
                        {
                            "name": "Blank",
                            "filename": "Blank",
                            "iconCode": "\\ue9fe",
                            "categories": [],
                        }
                    ]
                },
                f,
            )

        tpl.add_template_entry(DEVICE, "Custom.svg", ["Lines"])
        with pytest.raises(tpl.StockTemplateNameConflictError):
            tpl.rename_template_entry(DEVICE, "Custom.svg", "Blank.svg")

    def test_rename_template_entry_allows_revert_to_previous_synced_name(self, tmp_path):
        # Simulate a polluted backup where a previously synced custom stem appears.
        backup_path = tpl.get_device_templates_backup_path(DEVICE)
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "templates": [
                        {
                            "name": "Original",
                            "filename": "Original",
                            "iconCode": "\\ue9fe",
                            "categories": [],
                        }
                    ]
                },
                f,
            )

        tpl.save_templates_json(
            DEVICE,
            {
                "templates": [
                    {
                        "name": "Original",
                        "filename": "Original",
                        "iconCode": "\\ue9fe",
                        "categories": ["Lines"],
                    }
                ]
            },
        )
        mf.add_or_update_template_entry(DEVICE, "Original.svg", ["Lines"], "\ue9fe")
        mf.mark_synced(DEVICE)

        tpl.rename_template_entry(DEVICE, "Original.svg", "Temp.svg")
        # Reverting to the previous synced filename must be allowed.
        tpl.rename_template_entry(DEVICE, "Temp.svg", "Original.svg")

        entry = tpl.get_template_entry(DEVICE, "Original.svg")
        assert entry is not None
        assert entry["filename"] == "Original"


class TestGetBackupStems:
    def test_returns_empty_when_no_backup(self):
        assert tpl.get_backup_stems(DEVICE) == set()

    def test_returns_stems_from_backup(self, tmp_path):
        backup_path = tpl.get_device_templates_backup_path(DEVICE)
        import json as _json

        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        with open(backup_path, "w", encoding="utf-8") as f:
            _json.dump(
                {
                    "templates": [
                        {"filename": "Blank", "name": "Blank"},
                        {"filename": "Lines", "name": "Lines"},
                    ]
                },
                f,
            )
        stems = tpl.get_backup_stems(DEVICE)
        assert stems == {"Blank", "Lines"}

    def test_returns_empty_on_malformed_backup(self, tmp_path):
        backup_path = tpl.get_device_templates_backup_path(DEVICE)
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write("not valid json {{{")
        assert tpl.get_backup_stems(DEVICE) == set()


# ---------------------------------------------------------------------------
# Remote helpers
# ---------------------------------------------------------------------------


class TestUploadTemplateToTablet:
    def _setup_svg(self, tmp_path):
        tpl.save_device_template(DEVICE, SVG_CONTENT, "Red.svg")

    def test_happy_path(self, tmp_path):
        self._setup_svg(tmp_path)
        with (
            patch("src.templates.upload_file_ssh", return_value=(True, "ok")) as mock_up,
            patch("src.templates.run_ssh_cmd") as mock_cmd,
        ):
            ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is True
        assert msg == "ok"
        assert mock_up.call_count == 1
        mock_cmd.assert_called_once()

    def test_svg_upload_failure(self, tmp_path):
        self._setup_svg(tmp_path)
        with patch("src.templates.upload_file_ssh", return_value=(False, "denied")):
            ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is False
        assert "upload_svg_failed" in msg

    def test_restart_failure(self, tmp_path):
        self._setup_svg(tmp_path)
        with (
            patch("src.templates.upload_file_ssh", return_value=(True, "ok")),
            patch("src.templates.run_ssh_cmd", side_effect=Exception("ssh error")),
        ):
            ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", DEVICE, "Red.svg")
        assert ok is False
        assert "restart_failed" in msg

    def test_missing_local_svg(self):
        with patch("src.templates.upload_file_ssh"), patch("src.templates.run_ssh_cmd"):
            ok, msg = tpl.upload_template_to_tablet("1.2.3.4", "pw", DEVICE, "Ghost.svg")
        assert ok is False
        assert "read_local_failed" in msg


class TestDeleteTemplateFromTablet:
    def test_happy_path_with_json_upload(self, tmp_path):
        json_path = tmp_path / DEVICE / "templates.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text('{"templates":[]}', encoding="utf-8")

        with (
            patch("src.templates.run_ssh_cmd", return_value=("", "")) as mock_cmd,
            patch("src.templates.upload_file_ssh", return_value=(True, "ok")) as mock_up,
        ):
            ok, msg = tpl.delete_template_from_tablet("1.2.3.4", "pw", DEVICE, "my file.svg")

        assert ok is True
        assert msg == "ok"
        assert mock_cmd.call_count == 2
        mock_up.assert_called_once()

    def test_remote_delete_failure(self):
        with patch("src.templates.run_ssh_cmd", return_value=("", "permission denied")):
            ok, msg = tpl.delete_template_from_tablet("1.2.3.4", "pw", DEVICE, "my.svg")
        assert ok is False
        assert "delete_remote_failed" in msg

    def test_json_upload_failure(self, tmp_path):
        json_path = tmp_path / DEVICE / "templates.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text('{"templates":[]}', encoding="utf-8")

        with (
            patch("src.templates.run_ssh_cmd", return_value=("", "")),
            patch("src.templates.upload_file_ssh", return_value=(False, "disk full")),
        ):
            ok, msg = tpl.delete_template_from_tablet("1.2.3.4", "pw", DEVICE, "my.svg")
        assert ok is False
        assert "upload_json_failed" in msg


# ---------------------------------------------------------------------------
# ensure_remote_template_dirs
# ---------------------------------------------------------------------------


class TestEnsureRemoteTemplateDirs:
    def test_success(self):
        with patch("src.templates.run_ssh_cmd", return_value=("ok", "")):
            ok, msg = tpl.ensure_remote_template_dirs(
                "1.2.3.4", "pw", "/remote/custom", "/remote/tpl"
            )
        assert ok is True

    def test_exception_returns_false(self):
        with patch("src.templates.run_ssh_cmd", side_effect=Exception("ssh error")):
            ok, msg = tpl.ensure_remote_template_dirs(
                "1.2.3.4", "pw", "/remote/custom", "/remote/tpl"
            )
        assert ok is False
        assert "ssh error" in msg


# ---------------------------------------------------------------------------
# fetch_and_init_templates
# ---------------------------------------------------------------------------


class TestFetchAndInitTemplates:
    def test_download_failure(self):
        with patch("src.templates.download_file_ssh", return_value=(None, "timeout")):
            ok, msg = tpl.fetch_and_init_templates("1.2.3.4", "pw", DEVICE)
        assert ok is False
        assert "download_failed" in msg

    def test_backup_parse_failed(self):
        with patch("src.templates.download_file_ssh", return_value=(b"not-valid-json", "")):
            ok, msg = tpl.fetch_and_init_templates("1.2.3.4", "pw", DEVICE)
        assert ok is False
        assert "backup_parse_failed" in msg

    def test_happy_path_no_local_svgs(self, tmp_path):
        # Ensure the device directory exists so the backup file can be written
        (tmp_path / DEVICE).mkdir(parents=True, exist_ok=True)
        remote_json = json.dumps({"templates": []}).encode()
        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch("src.templates._list_remote_stock_template_stems", return_value=(True, set())),
        ):
            ok, msg = tpl.fetch_and_init_templates("1.2.3.4", "pw", DEVICE)
        assert ok is True
        assert "fetched" in msg

    def test_appends_local_svgs_not_in_backup(self, tmp_path):
        svgs_dir = tmp_path / DEVICE / "templates"
        svgs_dir.mkdir(parents=True)
        (svgs_dir / "custom.svg").write_bytes(SVG_CONTENT)
        remote_json = json.dumps({"templates": []}).encode()
        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch("src.templates._list_remote_stock_template_stems", return_value=(True, set())),
        ):
            ok, msg = tpl.fetch_and_init_templates("1.2.3.4", "pw", DEVICE)
        assert ok is True
        assert "1 local custom template" in msg
        data = tpl.load_templates_json(DEVICE)
        assert any(t["filename"] == "custom" for t in data["templates"])

    def test_does_not_duplicate_existing_entries(self, tmp_path):
        svgs_dir = tmp_path / DEVICE / "templates"
        svgs_dir.mkdir(parents=True)
        (svgs_dir / "Blank.svg").write_bytes(SVG_CONTENT)
        remote_json = json.dumps(
            {
                "templates": [
                    {"name": "Blank", "filename": "Blank", "iconCode": "\ue9fe", "categories": []}
                ]
            }
        ).encode()
        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch(
                "src.templates._list_remote_stock_template_stems",
                return_value=(True, {"Blank"}),
            ),
        ):
            ok, msg = tpl.fetch_and_init_templates("1.2.3.4", "pw", DEVICE)
        assert ok is True
        assert "0 local custom template" in msg

    def test_include_remote_custom_downloads_files_and_appends_metadata(self, tmp_path):
        remote_json = json.dumps({"templates": []}).encode()
        remote_calls: list[str] = []

        def _download_side_effect(_ip, _pw, remote_path):
            remote_calls.append(remote_path)
            if remote_path.endswith("templates.json"):
                return remote_json, ""
            if remote_path.endswith("remote one.svg"):
                return SVG_CONTENT, ""
            return b'{"items":[]}', ""

        with (
            patch("src.templates.download_file_ssh", side_effect=_download_side_effect),
            patch(
                "src.templates._list_remote_custom_templates",
                return_value=(True, ["remote one.svg", "remote-two.template"]),
            ),
            patch("src.templates._list_remote_stock_template_stems", return_value=(True, set())),
        ):
            ok, msg = tpl.fetch_and_init_templates(
                "1.2.3.4", "pw", DEVICE, include_remote_custom_templates=True
            )
        assert ok is True
        assert "2 downloaded" in msg
        data = tpl.load_templates_json(DEVICE)
        assert any(t["filename"] == "remote one" for t in data["templates"])
        assert any(t["filename"] == "remote-two" for t in data["templates"])
        assert any(call.endswith("remote one.svg") for call in remote_calls)

    def test_include_remote_custom_returns_error_when_listing_fails(self):
        remote_json = json.dumps({"templates": []}).encode()
        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch(
                "src.templates._list_remote_custom_templates",
                return_value=(False, "ssh error"),
            ),
            patch("src.templates._list_remote_stock_template_stems", return_value=(True, set())),
        ):
            ok, msg = tpl.fetch_and_init_templates(
                "1.2.3.4", "pw", DEVICE, include_remote_custom_templates=True
            )
        assert ok is False
        assert "list_remote_custom_failed" in msg

    def test_refreshes_existing_backup_from_tablet_by_default(self, tmp_path):
        backup_path = tmp_path / DEVICE / "templates.backup.json"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(
            json.dumps(
                {
                    "templates": [
                        {
                            "name": "StockOnly",
                            "filename": "StockOnly",
                            "iconCode": "\\ue9fe",
                            "categories": [],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        remote_json = json.dumps(
            {
                "templates": [
                    {
                        "name": "Remote",
                        "filename": "Remote",
                        "iconCode": "\ue9ab",
                        "categories": ["Tablet", "Sketch"],
                    }
                ]
            }
        ).encode()

        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch(
                "src.templates._list_remote_stock_template_stems",
                return_value=(True, {"Remote"}),
            ),
        ):
            ok, msg = tpl.fetch_and_init_templates("1.2.3.4", "pw", DEVICE)

        assert ok is True
        assert "backup_refreshed" in msg
        with open(backup_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["templates"][0]["filename"] == "Remote"
        entry = tpl.get_template_entry(DEVICE, "Remote")
        assert entry is not None
        assert entry["iconCode"] == "\ue9ab"
        assert entry["categories"] == ["Sketch", "Tablet"]

    def test_overwrites_backup_when_requested(self, tmp_path):
        backup_path = tmp_path / DEVICE / "templates.backup.json"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(
            json.dumps({"templates": [{"name": "Old", "filename": "Old"}]}),
            encoding="utf-8",
        )
        remote_json = json.dumps({"templates": [{"name": "New", "filename": "New"}]}).encode()

        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch(
                "src.templates._list_remote_stock_template_stems",
                return_value=(True, {"New"}),
            ),
        ):
            ok, msg = tpl.fetch_and_init_templates(
                "1.2.3.4",
                "pw",
                DEVICE,
                overwrite_backup=True,
            )

        assert ok is True
        assert "backup_refreshed" in msg
        with open(backup_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["templates"][0]["filename"] == "New"

    def test_missing_backup_copies_remote_as_is_when_stock_only(self, tmp_path):
        remote_json = b'{"meta":{"format":2},"templates":[{"filename":"Blank","name":"Blank"}]}'
        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch(
                "src.templates._list_remote_stock_template_stems",
                return_value=(True, {"Blank"}),
            ),
        ):
            ok, msg = tpl.fetch_and_init_templates("1.2.3.4", "pw", DEVICE)

        assert ok is True
        assert "backup_refreshed" in msg
        backup_path = tmp_path / DEVICE / "templates.backup.json"
        assert backup_path.read_bytes() == remote_json

    def test_missing_backup_rebuilds_stock_only_from_remote_when_mixed(self, tmp_path):
        remote_json = json.dumps(
            {
                "templates": [
                    {"name": "Blank", "filename": "Blank"},
                    {"name": "Custom", "filename": "Custom"},
                ]
            }
        ).encode()
        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch(
                "src.templates._list_remote_stock_template_stems",
                return_value=(True, {"Blank"}),
            ),
        ):
            ok, msg = tpl.fetch_and_init_templates("1.2.3.4", "pw", DEVICE)

        assert ok is True
        assert "backup_rebuilt_stock_only" in msg
        backup_path = tmp_path / DEVICE / "templates.backup.json"
        with open(backup_path, encoding="utf-8") as f:
            backup_data = json.load(f)
        assert [entry["filename"] for entry in backup_data["templates"]] == ["Blank"]

    def test_existing_backup_is_preserved_when_remote_contains_custom(self, tmp_path):
        backup_path = tmp_path / DEVICE / "templates.backup.json"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(
            json.dumps({"templates": [{"name": "Blank", "filename": "Blank"}]}),
            encoding="utf-8",
        )

        remote_json = json.dumps(
            {
                "templates": [
                    {"name": "Blank", "filename": "Blank"},
                    {"name": "Custom", "filename": "Custom"},
                ]
            }
        ).encode()

        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch(
                "src.templates._list_remote_stock_template_stems",
                return_value=(True, {"Blank"}),
            ),
        ):
            ok, msg = tpl.fetch_and_init_templates("1.2.3.4", "pw", DEVICE)

        assert ok is True
        assert "backup_preserved" in msg
        with open(backup_path, encoding="utf-8") as f:
            backup_data = json.load(f)
        assert [entry["filename"] for entry in backup_data["templates"]] == ["Blank"]


# ---------------------------------------------------------------------------
# refresh_templates_backup_from_tablet
# ---------------------------------------------------------------------------


class TestRefreshTemplatesBackupFromTablet:
    def test_missing_backup_copies_remote_as_is_when_stock_only(self, tmp_path):
        remote_json = b'{"meta":{"schema":3},"templates":[{"filename":"Blank","name":"Blank"}]}'
        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch(
                "src.templates._list_remote_stock_template_stems",
                return_value=(True, {"Blank"}),
            ),
        ):
            ok, msg = tpl.refresh_templates_backup_from_tablet("1.2.3.4", "pw", DEVICE)

        assert ok is True
        assert msg == "backup_refreshed"
        backup_path = tmp_path / DEVICE / "templates.backup.json"
        assert backup_path.read_bytes() == remote_json

    def test_existing_backup_preserved_when_remote_contains_custom(self, tmp_path):
        backup_path = tmp_path / DEVICE / "templates.backup.json"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        original_backup = b'{"templates":[{"filename":"Blank","name":"Blank"}]}'
        backup_path.write_bytes(original_backup)

        remote_json = b'{"templates":[{"filename":"Blank","name":"Blank"},{"filename":"Custom","name":"Custom"}]}'
        with (
            patch("src.templates.download_file_ssh", return_value=(remote_json, "")),
            patch(
                "src.templates._list_remote_stock_template_stems",
                return_value=(True, {"Blank"}),
            ),
        ):
            ok, msg = tpl.refresh_templates_backup_from_tablet("1.2.3.4", "pw", DEVICE)

        assert ok is True
        assert msg == "backup_preserved_remote_contains_custom"
        assert backup_path.read_bytes() == original_backup

    def test_reset_and_initialize_deletes_local_state_before_reimport(self, tmp_path):
        device_dir = tmp_path / DEVICE
        templates_dir = device_dir / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)
        (templates_dir / "old.svg").write_bytes(SVG_CONTENT)
        (templates_dir / "old.template").write_bytes(b'{"categories": ["Old"]}')
        (device_dir / "templates.json").write_text('{"templates": []}', encoding="utf-8")
        (device_dir / "templates.backup.json").write_text('{"templates": []}', encoding="utf-8")
        (device_dir / "manifest.json").write_text(
            '{"version": 1, "lastSync": null, "templates": []}',
            encoding="utf-8",
        )

        with patch(
            "src.templates.fetch_and_init_templates",
            return_value=(True, "fetched"),
        ) as mock_fetch:
            ok, msg = tpl.reset_and_initialize_templates_from_tablet("1.2.3.4", "pw", DEVICE)

        assert ok is True
        assert "reset" in msg
        assert not any(templates_dir.iterdir())
        assert not (device_dir / "templates.json").exists()
        assert not (device_dir / "templates.backup.json").exists()
        assert not (device_dir / "manifest.json").exists()
        mock_fetch.assert_called_once_with(
            "1.2.3.4",
            "pw",
            DEVICE,
            include_remote_custom_templates=True,
            overwrite_backup=True,
        )


# ---------------------------------------------------------------------------
# is_templates_dirty (manifest-based)
# ---------------------------------------------------------------------------


class TestIsDirty:
    def test_missing_manifest_not_dirty(self):
        assert tpl.is_templates_dirty(DEVICE) is False

    def test_pending_entry_is_dirty(self):
        tpl.add_template_entry(DEVICE, "A.svg", ["Lines"])
        assert tpl.is_templates_dirty(DEVICE) is True

    def test_deleted_entry_is_dirty(self):
        tpl.add_template_entry(DEVICE, "A.svg", ["Lines"])
        tpl.remove_template_entry(DEVICE, "A.svg")
        assert tpl.is_templates_dirty(DEVICE) is True


# ---------------------------------------------------------------------------
# .template file support in list_device_templates
# ---------------------------------------------------------------------------


class TestListDeviceTemplatesJsonTemplates:
    def test_includes_template_extension(self):
        tpl.save_device_template(DEVICE, b'{"orientation":"portrait"}', "My.template")
        result = tpl.list_device_templates(DEVICE)
        assert "My.template" in result

    def test_includes_both_svg_and_template(self):
        tpl.save_device_template(DEVICE, SVG_CONTENT, "A.svg")
        tpl.save_device_template(DEVICE, b'{"orientation":"portrait"}', "B.template")
        result = tpl.list_device_templates(DEVICE)
        assert "A.svg" in result
        assert "B.template" in result

    def test_excludes_txt_when_template_present(self):
        tpl.save_device_template(DEVICE, b'{"orientation":"portrait"}', "C.template")
        tpl.save_device_template(DEVICE, b"notes", "readme.txt")
        result = tpl.list_device_templates(DEVICE)
        assert "readme.txt" not in result
        assert "C.template" in result


# ---------------------------------------------------------------------------
# JSON template storage helpers (save / load / list)
# ---------------------------------------------------------------------------


class TestJsonTemplateStorage:
    """save_json_template / load_json_template / list_json_templates all use the
    shared templates dir (data/<device>/templates/), not a separate subdir."""

    _CONTENT = '{"orientation": "portrait", "items": []}'

    def test_save_and_load_roundtrip(self):
        tpl.save_json_template(DEVICE, "T1.template", self._CONTENT)
        assert tpl.load_json_template(DEVICE, "T1.template") == self._CONTENT

    def test_save_goes_to_templates_dir(self, tmp_path):
        tpl.save_json_template(DEVICE, "T2.template", self._CONTENT)
        expected_path = tmp_path / DEVICE / "templates" / "T2.template"
        assert expected_path.exists()

    def test_list_json_templates_returns_only_template_files(self):
        tpl.save_device_template(DEVICE, SVG_CONTENT, "grid.svg")
        tpl.save_json_template(DEVICE, "lines.template", self._CONTENT)
        result = tpl.list_json_templates(DEVICE)
        assert "lines.template" in result
        assert "grid.svg" not in result

    def test_list_json_templates_empty(self):
        assert tpl.list_json_templates(DEVICE) == []

    def test_list_json_templates_sorted(self):
        tpl.save_json_template(DEVICE, "z.template", self._CONTENT)
        tpl.save_json_template(DEVICE, "a.template", self._CONTENT)
        result = tpl.list_json_templates(DEVICE)
        assert result == ["a.template", "z.template"]

    def test_no_separate_json_templates_subdir_created(self, tmp_path):
        tpl.save_json_template(DEVICE, "T3.template", self._CONTENT)
        separate_dir = tmp_path / DEVICE / "json_templates"
        assert not separate_dir.exists()

    def test_stem_handles_template_extension(self):
        assert tpl._stem("MyFile.template") == "MyFile"
        assert tpl._stem("MyFile.TEMPLATE") == "MyFile"
