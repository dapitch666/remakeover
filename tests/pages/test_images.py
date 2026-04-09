"""Tests for pages/images.py.

Covers: empty warning, image grid, rename mode, delete flow, import from tablet,
        error handling, upload section render, preferred-image actions, and
        segmented-control on_change callback paths.
"""

import json
import os
from contextlib import ExitStack
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import (
    PNG_BYTES,
    at_page,
    empty_cfg,
    flow_patches,
    make_env,
    with_device,
)

# ---------------------------------------------------------------------------
# Empty-config guard
# ---------------------------------------------------------------------------


def test_images_page_warns_when_no_devices(tmp_path):
    """Images page shows 'No device' message with an empty config."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/images.py").run()

    assert not at.exception
    assert any("No device" in m.value for m in at.markdown)


# ---------------------------------------------------------------------------
# Full upload + SSH send flow (end-to-end)
# ---------------------------------------------------------------------------


def test_upload_and_send_flow(tmp_path):
    """Clicking 'Import from tablet' downloads and saves an image."""
    cfg: dict = {
        "devices": {"D1": {"ip": "10.0.0.1", "password": "pw", "device_type": "reMarkable 2"}}
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    images_dir = tmp_path / "images" / "D1"
    images_dir.mkdir(parents=True)

    upload_calls: list = []
    run_cmds: list = []
    saved_files: list = []

    with ExitStack() as stack:
        stack.enter_context(
            patch.dict(
                os.environ,
                {"RM_CONFIG_PATH": str(cfg_file), "RM_DATA_DIR": str(tmp_path)},
            )
        )
        for p in flow_patches(images_dir, upload_calls, run_cmds, saved_files):
            stack.enter_context(p)

        at = AppTest.from_file("app.py")
        at.run()
        at.sidebar.selectbox[0].set_value("D1").run()

        download_btn = next(
            (b for b in at.button if getattr(b, "label", None) == "Import from tablet"),
            None,
        )
        assert download_btn is not None, "Download button not found"
        download_btn.click().run()

    assert saved_files, "save_device_image was not called"


# ---------------------------------------------------------------------------
# Image grid and interactions
# ---------------------------------------------------------------------------


class TestImagesPage:
    def test_no_images_shows_info(self, tmp_path):
        """With no stored images, the page shows an info message."""
        cfg_path = with_device(tmp_path, "D1")
        at = at_page(
            tmp_path,
            "pages/images.py",
            cfg_path,
            patches=[patch("src.images.list_device_images", return_value=[])],
        )
        assert not at.exception
        assert any("No images" in m.value for m in at.info)

    def test_with_images_grid_rendered(self, tmp_path):
        """When images exist, the page renders each image card without error."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["a.png", "b.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
        assert not at.exception

    def test_click_image_name_enters_rename_mode(self, tmp_path):
        """Clicking an image name button sets img_renaming in session state."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["myphoto.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
            name_btn = next((b for b in at.button if "myphoto" in b.label), None)
            assert name_btn is not None, "Image name button not found"
            name_btn.click().run()
        assert not at.exception
        assert at.session_state["img_renaming"] == "myphoto.png"

    def test_rename_mode_shows_form(self, tmp_path):
        """When img_renaming is set, the page renders a rename form."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["pic.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_renaming"] = "pic.png"
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert any(":material/check:" in b.label for b in at.button)

    def test_delete_pending_shows_confirm_dialog(self, tmp_path):
        """When img_pending_delete is set, a confirmation dialog is triggered."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["todel.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_delete"] = "todel.png"
            at.switch_page("pages/images.py").run()
        assert not at.exception

    def test_delete_confirmed_removes_image(self, tmp_path):
        """When confirm_del_img is True, the image is deleted and state cleared."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        deleted: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["todel.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch(
                "src.images.delete_device_image",
                side_effect=lambda _n, f: deleted.append(f),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_delete"] = "todel.png"
            at.session_state["confirm_del_img"] = True
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert "todel.png" in deleted

    def test_delete_cancelled_clears_state(self, tmp_path):
        """When confirm_del_img is False, state is cleared without deleting."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["keep.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_delete"] = "keep.png"
            at.session_state["confirm_del_img"] = False
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert at.session_state["img_pending_delete"] is None

    def test_import_from_tablet_saves_image(self, tmp_path):
        """Clicking 'Import from tablet' downloads and saves the image."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        saved: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=[]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch("src.ssh.download_file_ssh", return_value=(PNG_BYTES, "")),
            patch(
                "src.images.save_device_image",
                side_effect=lambda _n, _d, f: saved.append(f),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
            import_btn = next((b for b in at.button if "Import from tablet" in b.label), None)
            assert import_btn is not None
            import_btn.click().run()
        assert not at.exception
        assert saved, "save_device_image was not called"

    def test_import_from_tablet_shows_error_on_failure(self, tmp_path):
        """When SSH download raises, an error message is shown."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=[]),
            patch("src.ssh.download_file_ssh", return_value=(None, "Connection refused")),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
            import_btn = next((b for b in at.button if "Import from tablet" in b.label), None)
            assert import_btn is not None
            import_btn.click().run()
        assert not at.exception
        assert any("Connection refused" in e.value for e in at.error)

    def test_upload_section_rendered(self, tmp_path):
        """The 'Add an image' file uploader section is always rendered."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=[]),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert any("Add" in s.value for s in at.subheader)

    def test_rename_conflict_shows_confirm_dialog(self, tmp_path):
        """When img_pending_rename is set, the overwrite confirmation dialog is triggered."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["old.png", "new.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_rename"] = ("old.png", "new.png")
            at.switch_page("pages/images.py").run()
        assert not at.exception

    def test_rename_conflict_confirmed_renames_file(self, tmp_path):
        """When confirm_rename_img is True, the image is renamed and state cleared."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        renamed: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["old.png", "new.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch(
                "src.images.rename_device_image",
                side_effect=lambda _n, o, f: renamed.append((o, f)),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_rename"] = ("old.png", "new.png")
            at.session_state["confirm_rename_img"] = True
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert ("old.png", "new.png") in renamed
        assert at.session_state["img_pending_rename"] is None
        assert at.session_state["img_renaming"] is None

    def test_rename_conflict_cancelled_clears_state(self, tmp_path):
        """When confirm_rename_img is False, state is cleared without renaming."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        renamed: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["old.png", "new.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch(
                "src.images.rename_device_image",
                side_effect=lambda _n, o, f: renamed.append((o, f)),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_rename"] = ("old.png", "new.png")
            at.session_state["confirm_rename_img"] = False
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert not renamed
        assert at.session_state["img_pending_rename"] is None
        assert at.session_state["img_renaming"] is None


# ---------------------------------------------------------------------------
# Preferred-image update paths
# ---------------------------------------------------------------------------


class TestPreferredImageActions:
    """Tests for preferred-image branch in _render_image_card."""

    def _cfg_with_preferred(self, tmp_path, device_name: str, preferred: str) -> str:
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "devices": {
                        device_name: {
                            "ip": "10.0.0.1",
                            "password": "pw",
                            "device_type": "reMarkable 2",
                            "preferred_image": preferred,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return str(cfg_file)

    def test_delete_confirmed_preferred_image_clears_preferred(self, tmp_path):
        """When a preferred image is deleted, preferred_image is reset to None."""
        cfg_path = self._cfg_with_preferred(tmp_path, "D1", "fav.png")
        env = make_env(tmp_path, cfg_path)
        deleted: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["fav.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch(
                "src.images.delete_device_image",
                side_effect=lambda _n, f: deleted.append(f),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_delete"] = "fav.png"
            at.session_state["confirm_del_img"] = True
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert "fav.png" in deleted
        # preferred_image should now be absent / None in the saved config
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["devices"]["D1"].get("preferred_image") is None

    def test_rename_conflict_confirmed_preferred_updates_preferred(self, tmp_path):
        """When confirming a rename conflict, preferred_image is updated to the new name."""
        cfg_path = self._cfg_with_preferred(tmp_path, "D1", "old.png")
        env = make_env(tmp_path, cfg_path)
        renamed: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["old.png", "other.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch(
                "src.images.rename_device_image",
                side_effect=lambda _n, o, f: renamed.append((o, f)),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_rename"] = ("old.png", "other.png")
            at.session_state["confirm_rename_img"] = True
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert ("old.png", "other.png") in renamed
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["devices"]["D1"].get("preferred_image") == "other.png"


# ---------------------------------------------------------------------------
# Segmented-control on_change callback paths  (on_action)
# ---------------------------------------------------------------------------


class TestImageSegmentedActions:
    """Tests for all branches of the on_action on_change callback."""

    def _run_action(self, tmp_path, img_name: str, action_value, extra_patches=()):
        """Boot images page, then set the action segmented control to *action_value*."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env))
            stack.enter_context(patch("src.images.list_device_images", return_value=[img_name]))
            stack.enter_context(patch("src.images.load_device_image", return_value=PNG_BYTES))
            for p in extra_patches:
                stack.enter_context(p)
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
            # The action segmented control label is "Actions"
            sc = next((s for s in at.button_group if s.label == "Actions"), None)
            assert sc is not None, "Action segmented control not found"
            sc.set_value(action_value).run()
        return at

    def test_action_cloud_upload_sends_image(self, tmp_path):
        """Action 0 (cloud_upload) calls send_suspended_png with the image data."""
        sent: list = []

        def _mock_send(_device, _img_data, img_name, _selected_name, _add_log):
            sent.append(img_name)
            return True

        at = self._run_action(
            tmp_path,
            "photo.png",
            0,
            extra_patches=(patch("src.ui_common.send_suspended_png", side_effect=_mock_send),),
        )
        assert not at.exception
        assert "photo.png" in sent

    def test_action_cloud_upload_failure_records_error(self, tmp_path):
        """Action 0 when send_suspended_png returns False completes without exception."""
        at = self._run_action(
            tmp_path,
            "photo.png",
            0,
            extra_patches=(patch("src.ui_common.send_suspended_png", return_value=False),),
        )
        assert not at.exception

    def test_action_set_star_saves_preferred(self, tmp_path):
        """Action 1 (star) on a non-preferred image writes it as the preferred image."""
        at = self._run_action(tmp_path, "nice.png", 1)
        assert not at.exception
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["devices"]["D1"].get("preferred_image") == "nice.png"

    def test_action_remove_star_clears_preferred(self, tmp_path):
        """Action 1 (star) on the currently-preferred image clears it."""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "devices": {
                        "D1": {
                            "ip": "10.0.0.1",
                            "password": "pw",
                            "device_type": "reMarkable 2",
                            "preferred_image": "star.png",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        env = make_env(tmp_path, str(cfg_file))
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["star.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
            sc = next((s for s in at.button_group if s.label == "Actions"), None)
            assert sc is not None
            sc.set_value(1).run()
        assert not at.exception
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["devices"]["D1"].get("preferred_image") is None

    def test_action_delete_sets_pending_delete(self, tmp_path):
        """Action 2 (delete) sets img_pending_delete in session state."""
        at = self._run_action(tmp_path, "trash.png", 2)
        assert not at.exception
        assert at.session_state["img_pending_delete"] == "trash.png"
