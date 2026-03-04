"""Tests for pages/images.py.

Covers: empty warning, image grid, rename mode, delete flow, import from tablet,
        error handling, and upload section render.
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
    """Images page shows 'Aucun appareil' message with an empty config."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/images.py").run()

    assert not at.exception
    assert any("Aucun appareil" in m.value for m in at.markdown)


# ---------------------------------------------------------------------------
# Full upload + SSH send flow (end-to-end)
# ---------------------------------------------------------------------------


def test_upload_and_send_flow(tmp_path):
    """Clicking 'Importer depuis la tablette' downloads and saves an image."""
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
            (b for b in at.button if getattr(b, "label", None) == "Importer depuis la tablette"),
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
        assert any("Aucune image" in m.value for m in at.info)

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
                side_effect=lambda n, f: deleted.append(f),
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
        """Clicking 'Importer depuis la tablette' downloads and saves the image."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        saved: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.images.list_device_images", return_value=[]),
            patch("src.images.load_device_image", return_value=PNG_BYTES),
            patch("src.ssh.download_file_ssh", return_value=PNG_BYTES),
            patch(
                "src.images.save_device_image",
                side_effect=lambda n, d, f: saved.append(f),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
            import_btn = next(
                (b for b in at.button if "Importer depuis la tablette" in b.label), None
            )
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
            patch("src.ssh.download_file_ssh", side_effect=Exception("Connection refused")),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/images.py").run()
            import_btn = next(
                (b for b in at.button if "Importer depuis la tablette" in b.label), None
            )
            assert import_btn is not None
            import_btn.click().run()
        assert not at.exception
        assert any("Connection refused" in e.value for e in at.error)

    def test_upload_section_rendered(self, tmp_path):
        """The 'Ajouter une image' file uploader section is always rendered."""
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
        assert any("Ajouter" in s.value for s in at.subheader)
