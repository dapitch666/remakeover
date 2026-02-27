import os
import json
import base64
from contextlib import ExitStack
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

# a minimal valid 1x1 PNG used as synthetic SSH download payload
PNG_BYTES = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


def _flow_patches(images_dir, upload_calls, run_cmds, saved_files):
    """Return a list of patch() context managers for all src.* side-effectful calls."""

    def _save_device_image(device_name, img_data, filename):
        out = os.path.join(str(images_dir), filename)
        with open(out, "wb") as f:
            f.write(img_data)
        saved_files.append(out)
        return True

    def _load_device_image(device_name, img_name):
        p = os.path.join(str(images_dir), img_name)
        return open(p, "rb").read() if os.path.exists(p) else b""

    return [
        patch("src.ssh.test_ssh_connection", return_value=(True, "")),
        patch("src.ssh.upload_file_ssh",
              side_effect=lambda ip, pw, blob, path: upload_calls.append((ip, path)) or (True, "ok")),
        patch("src.ssh.download_file_ssh", return_value=PNG_BYTES),
        patch("src.ssh.run_ssh_cmd",
              side_effect=lambda ip, pw, cmds: run_cmds.append((ip, tuple(cmds)))),
        patch("src.images.process_image", return_value=b"processed"),
        patch("src.images.get_device_images_dir", return_value=str(images_dir)),
        patch("src.images.list_device_images",
              side_effect=lambda name: sorted(os.listdir(str(images_dir)))),
        patch("src.images.save_device_image", side_effect=_save_device_image),
        patch("src.images.load_device_image", side_effect=_load_device_image),
        patch("src.images.delete_device_image", return_value=True),
        patch("src.images.rename_device_image", return_value=True),
        patch("src.maintenance.run_maintenance", return_value={"ok": True}),
        patch("src.dialog.confirm", return_value=True),
    ]


def test_upload_and_send_flow(tmp_path):
    cfg = {
        "devices": {
            "D1": {"ip": "10.0.0.1", "password": "pw", "device_type": "reMarkable 2"}
        }
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    images_dir = tmp_path / "images" / "D1"
    images_dir.mkdir(parents=True)

    upload_calls = []
    run_cmds = []
    saved_files = []

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {"RM_CONFIG_PATH": str(cfg_file)}))
        for p in _flow_patches(images_dir, upload_calls, run_cmds, saved_files):
            stack.enter_context(p)

        at = AppTest.from_file("app.py")
        at.run()
        at.selectbox[0].set_value("D1").run()

        download_btn = next(
            (b for b in at.button if getattr(b, "label", None) == "Importer depuis la tablette"),
            None,
        )
        assert download_btn is not None, "Download button not found"
        download_btn.click().run()

    assert saved_files, "save_device_image was not called"


def test_run_maintenance_flow(tmp_path):
    cfg = {
        "devices": {
            "D1": {"ip": "10.0.0.1", "password": "pw", "device_type": "reMarkable 2", "carousel": True}
        }
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    images_dir = tmp_path / "images" / "D1"
    images_dir.mkdir(parents=True)

    upload_calls = []
    run_cmds = []
    saved_files = []
    maintenance_calls = []

    patches = _flow_patches(images_dir, upload_calls, run_cmds, saved_files)
    patches[11] = patch(
        "src.maintenance.run_maintenance",
        side_effect=lambda name, dev, image=None, step_fn=None, progress_fn=None, toast_fn=None, log_fn=None:
            maintenance_calls.append((name, dev)) or {"ok": True},
    )

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {"RM_CONFIG_PATH": str(cfg_file)}))
        for p in patches:
            stack.enter_context(p)

        at = AppTest.from_file("app.py")
        at.run()
        at.selectbox[0].set_value("D1").run()

        mbtn = next(
            (b for b in at.button if getattr(b, "label", None) == "Lancer le script complet"),
            None,
        )
        assert mbtn is not None, "Maintenance button not found"
        mbtn.click().run()

    assert maintenance_calls, "run_maintenance was not called"
