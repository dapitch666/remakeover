"""Tests for pages/images.py.

Covers: empty warning, image grid, rename mode, delete flow, import from device,
        error handling, upload section render, preferred-image actions, and
        segmented-control on_change callback paths.
"""

import json
import os
from contextlib import ExitStack
from types import SimpleNamespace
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
    assert any("No device" in w.value for w in at.warning)


# ---------------------------------------------------------------------------
# Full upload + SSH send flow (end-to-end)
# ---------------------------------------------------------------------------


def test_upload_and_send_flow(tmp_path):
    """Clicking 'Import from device' downloads and saves an image."""
    cfg: dict = {
        "devices": {
            "D1": {
                "ip": "10.0.0.1",
                "password": "pw",
                "device_type": "reMarkable 2",
                "sleep_screen_enabled": True,
            }
        }
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    images_dir = tmp_path / "images" / "D1"
    images_dir.mkdir(parents=True)

    upload_calls: list = []
    run_cmds: list = []
    saved_files: list = []

    # noinspection PyAbstractClass
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
            (b for b in at.button if getattr(b, "label", None) == "Import from device"),
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
            patch("src.images.list_device_images", return_value=["MyImage.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
            name_btn = next((b for b in at.button if "MyImage" in b.label), None)
            assert name_btn is not None, "Image name button not found"
            name_btn.click().run()
        assert not at.exception
        assert at.session_state["img_renaming"] == "MyImage.png"

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
            patch("src.images.list_device_images", return_value=["image2.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_delete"] = "image2.png"
            at.switch_page("pages/images.py").run()
        assert not at.exception

    def test_delete_confirmed_removes_image(self, tmp_path):
        """When confirm_del_img is True, the image is deleted and state cleared."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        deleted: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["image2.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch(
                "src.images.delete_device_image",
                side_effect=lambda _n, f: deleted.append(f),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_delete"] = "image2.png"
            at.session_state["confirm_del_img"] = True
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert "image2.png" in deleted

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

    def test_import_from_device_saves_image(self, tmp_path):
        """Clicking 'Import from device' downloads and saves the image."""
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
            import_btn = next((b for b in at.button if "Import from device" in b.label), None)
            assert import_btn is not None
            import_btn.click().run()
        assert not at.exception
        assert saved, "save_device_image was not called"

    def test_import_from_device_shows_error_on_failure(self, tmp_path):
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
            import_btn = next((b for b in at.button if "Import from device" in b.label), None)
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
# sleep_screen_enabled gating
# ---------------------------------------------------------------------------


class TestSleepScreenGating:
    def test_import_button_disabled_when_sleep_screen_not_enabled(self, tmp_path):
        """'Import from device' is disabled when sleep_screen_enabled is False."""
        cfg_path = with_device(tmp_path, "D1", sleep_screen_enabled=False)
        at = at_page(
            tmp_path,
            "pages/images.py",
            cfg_path,
            patches=[patch("src.images.list_device_images", return_value=[])],
        )
        assert not at.exception
        btn = next((b for b in at.button if "Import from device" in b.label), None)
        assert btn is not None
        assert btn.disabled is True

    def test_restore_button_disabled_when_sleep_screen_not_enabled(self, tmp_path):
        """'Restore default' is disabled when sleep_screen_enabled is False."""
        cfg_path = with_device(tmp_path, "D1", sleep_screen_enabled=False)
        at = at_page(
            tmp_path,
            "pages/images.py",
            cfg_path,
            patches=[patch("src.images.list_device_images", return_value=[])],
        )
        assert not at.exception
        btn = next((b for b in at.button if "Restore default" in b.label), None)
        assert btn is not None
        assert btn.disabled is True

    def test_import_button_enabled_when_sleep_screen_enabled(self, tmp_path):
        """'Import from device' is enabled when sleep_screen_enabled is True."""
        cfg_path = with_device(tmp_path, "D1", sleep_screen_enabled=True)
        at = at_page(
            tmp_path,
            "pages/images.py",
            cfg_path,
            patches=[patch("src.images.list_device_images", return_value=[])],
        )
        assert not at.exception
        btn = next((b for b in at.button if "Import from device" in b.label), None)
        assert btn is not None
        assert btn.disabled is False

    def test_send_image_sets_sleep_screen_enabled_in_config(self, tmp_path):
        """Sending an image via segmented control sets sleep_screen_enabled=True in config."""
        cfg_path = with_device(tmp_path, "D1", sleep_screen_enabled=True)
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["photo.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch("src.images.send_suspended_png", return_value=True),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
            sc = next((s for s in at.button_group if s.label == "Actions"), None)
            assert sc is not None
            sc.set_value(0).run()
        assert not at.exception
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["devices"]["D1"]["sleep_screen_enabled"] is True

    def test_rollback_clears_sleep_screen_enabled_in_config(self, tmp_path):
        """A successful rollback sets sleep_screen_enabled=False in config."""
        cfg_path = with_device(tmp_path, "D1", sleep_screen_enabled=True)
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=[]),
            patch("src.images.rollback_sleep_screen", return_value=True),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_rollback_D1"] = True
            at.session_state["confirm_rollback_D1"] = True
            at.switch_page("pages/images.py").run()
        assert not at.exception
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["devices"]["D1"]["sleep_screen_enabled"] is False


# ---------------------------------------------------------------------------
# Segmented-control on_change callback paths  (on_action)
# ---------------------------------------------------------------------------


class TestImageSegmentedActions:
    """Tests for all branches of the on_action on_change callback."""

    @staticmethod
    def _run_action(tmp_path, img_name: str, action_value, extra_patches=()):
        """Boot images page, then set the action segmented control to *action_value*."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        # noinspection PyAbstractClass
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

        def _mock_send(_device, _img_data, img_name, _add_log):
            sent.append(img_name)
            return True

        at = self._run_action(
            tmp_path,
            "photo.png",
            0,
            extra_patches=(patch("src.images.send_suspended_png", side_effect=_mock_send),),
        )
        assert not at.exception
        assert "photo.png" in sent

    def test_action_cloud_upload_failure_records_error(self, tmp_path):
        """Action 0 when send_suspended_png returns False completes without exception."""
        at = self._run_action(
            tmp_path,
            "photo.png",
            0,
            extra_patches=(patch("src.images.send_suspended_png", return_value=False),),
        )
        assert not at.exception

    def test_action_delete_sets_pending_delete(self, tmp_path):
        """Action 1 (delete) sets img_pending_delete in session state."""
        at = self._run_action(tmp_path, "trash.png", 1)
        assert not at.exception
        assert at.session_state["img_pending_delete"] == "trash.png"


# ---------------------------------------------------------------------------
# Multi-row grid layout
# ---------------------------------------------------------------------------


class TestGridLayout:
    def test_grid_multiple_rows_renders_without_error(self, tmp_path):
        """With more images than GRID_COLUMNS (5), the second row and its divider render."""
        # 6 images → two rows; the inter-row st.divider() fires for the first row
        images = [f"img{i}.png" for i in range(6)]
        cfg_path = with_device(tmp_path, "D1")
        at = at_page(
            tmp_path,
            "pages/images.py",
            cfg_path,
            patches=[
                patch("src.images.list_device_images", return_value=images),
                patch("src.images.load_device_image", return_value=PNG_BYTES),
            ],
        )
        assert not at.exception
        # All image name buttons should be present
        image_buttons = [b for b in at.button if any(f"img{i}" in b.label for i in range(6))]
        assert len(image_buttons) == 6


# ---------------------------------------------------------------------------
# Restore-default (rollback) button and dialog paths
# ---------------------------------------------------------------------------


class TestRollbackPaths:
    def test_restore_button_click_sets_pending_state(self, tmp_path):
        """Clicking 'Restore default' sets the rollback-pending flag in session state."""
        cfg_path = with_device(tmp_path, "D1", sleep_screen_enabled=True)
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=[]),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
            btn = next((b for b in at.button if "Restore default" in b.label), None)
            assert btn is not None
            btn.click().run()
        assert not at.exception
        assert at.session_state["img_pending_rollback_D1"] is True

    def test_rollback_cancelled_clears_state_without_rolling_back(self, tmp_path):
        """When the rollback dialog is declined, state is cleared and rollback is not called."""
        cfg_path = with_device(tmp_path, "D1", sleep_screen_enabled=True)
        env = make_env(tmp_path, cfg_path)
        rolled_back: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=[]),
            patch(
                "src.images.rollback_sleep_screen",
                side_effect=lambda d, log: rolled_back.append(d.name) or True,
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_rollback_D1"] = True
            at.session_state["confirm_rollback_D1"] = False
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert not rolled_back
        assert "img_pending_rollback_D1" not in at.session_state

    def test_rollback_failure_does_not_update_config(self, tmp_path):
        """When rollback_sleep_screen returns False, sleep_screen_enabled stays True."""
        cfg_path = with_device(tmp_path, "D1", sleep_screen_enabled=True)
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=[]),
            patch("src.images.rollback_sleep_screen", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_pending_rollback_D1"] = True
            at.session_state["confirm_rollback_D1"] = True
            at.switch_page("pages/images.py").run()
        assert not at.exception
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["devices"]["D1"]["sleep_screen_enabled"] is True


# ---------------------------------------------------------------------------
# Upload section: post-upload send-to-device confirmation paths
# ---------------------------------------------------------------------------


class TestUploadConfirmation:
    @staticmethod
    def _fake_uploaded_file(name: str = "upload.png"):
        """Minimal stand-in for a Streamlit UploadedFile (truthy, has .name).

        MagicMock.name is a property on NonCallableMock, so it cannot be shadowed
        by a simple attribute assignment. SimpleNamespace avoids that entirely.
        """
        return SimpleNamespace(name=name)

    def test_upload_confirm_true_sends_image(self, tmp_path):
        """When img_send_confirm is True, send_suspended_png is called with the saved data.

        file_uploader is patched to return a truthy fake so _render_upload_section's
        early-return guard is bypassed. process_image is mocked so Pillow never touches
        the fake object. The auto-save block then sets img_send_data_D1, and the
        pre-set img_send_confirm_D1=True triggers the send branch.
        """
        cfg_path = with_device(tmp_path, "D1", sleep_screen_enabled=True)
        env = make_env(tmp_path, cfg_path)
        sent: list = []
        with (
            patch.dict(os.environ, env),
            patch("streamlit.file_uploader", return_value=self._fake_uploaded_file()),
            patch("src.images.list_device_images", return_value=[]),
            patch("src.images.process_image", return_value=PNG_BYTES),
            patch("src.images.save_device_image"),
            patch(
                "src.images.send_suspended_png",
                side_effect=lambda _d, _data, name, _log: sent.append(name) or True,
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_send_confirm_D1"] = True
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert "upload.png" in sent

    def test_upload_confirm_false_clears_state_without_sending(self, tmp_path):
        """When img_send_confirm is False, send is skipped and confirmation state is cleared."""
        cfg_path = with_device(tmp_path, "D1", sleep_screen_enabled=True)
        env = make_env(tmp_path, cfg_path)
        sent: list = []
        with (
            patch.dict(os.environ, env),
            patch("streamlit.file_uploader", return_value=self._fake_uploaded_file()),
            patch("src.images.list_device_images", return_value=[]),
            patch("src.images.process_image", return_value=PNG_BYTES),
            patch("src.images.save_device_image"),
            patch(
                "src.images.send_suspended_png",
                side_effect=lambda _d, _data, name, _log: sent.append(name) or True,
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_send_confirm_D1"] = False
            at.switch_page("pages/images.py").run()
        assert not at.exception
        assert not sent
        assert "img_send_confirm_D1" not in at.session_state


# ---------------------------------------------------------------------------
# Inline rename: successful (non-conflicting) submission
# ---------------------------------------------------------------------------


class TestInlineRename:
    def test_rename_form_submit_calls_rename_device_image(self, tmp_path):
        """Submitting the rename form with a new, non-conflicting name renames the image."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        renamed: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["pic.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch(
                "src.images.rename_device_image",
                side_effect=lambda _n, old, new: renamed.append((old, new)),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_renaming"] = "pic.png"
            at.switch_page("pages/images.py").run()
            # Queue a new name in the text input, then submit the form
            at.text_input[0].set_value("new_pic")
            submit = next((b for b in at.button if ":material/check:" in b.label), None)
            assert submit is not None, "Form submit button not found"
            submit.click().run()
        assert not at.exception
        assert ("pic.png", "new_pic.png") in renamed

    def test_rename_form_submit_same_name_does_nothing(self, tmp_path):
        """Submitting the rename form with the same name skips the rename call."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        renamed: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["pic.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch(
                "src.images.rename_device_image",
                side_effect=lambda _n, old, new: renamed.append((old, new)),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_renaming"] = "pic.png"
            at.switch_page("pages/images.py").run()
            at.text_input[0].set_value("pic.png")
            submit = next((b for b in at.button if ":material/check:" in b.label), None)
            assert submit is not None
            submit.click().run()
        assert not at.exception
        assert not renamed

    def test_rename_form_submit_conflict_sets_pending_rename(self, tmp_path):
        """Submitting the rename form with a name that already exists sets img_pending_rename.

        This covers the conflict branch in do_rename: when the target name is already
        taken, rename_device_image is NOT called and img_pending_rename is set instead
        so the overwrite-confirmation dialog can be shown.
        """
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        renamed: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=["pic.png", "other.png"]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch(
                "src.images.rename_device_image",
                side_effect=lambda _n, old, new: renamed.append((old, new)),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["img_renaming"] = "pic.png"
            at.switch_page("pages/images.py").run()
            # "other" normalises to "other.png", which already exists
            at.text_input[0].set_value("other")
            submit = next((b for b in at.button if ":material/check:" in b.label), None)
            assert submit is not None
            submit.click().run()
        assert not at.exception
        assert not renamed, "rename_device_image should not be called on conflict"
        assert at.session_state["img_pending_rename"] == ("pic.png", "other.png")
