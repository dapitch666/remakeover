import sys
import types
import io
import os
import json
import tempfile
import base64
from types import ModuleType
from streamlit.testing.v1 import AppTest


def make_stub_modules(images_dir, upload_calls, run_cmds, maintenance_calls, saved_files):
    # SSH stub
    ssh = ModuleType("src.ssh")

    def test_ssh_connection(ip, password):
        return True, ""

    def upload_file_ssh(ip, password, img_blob, path):
        upload_calls.append((ip, path))
        return True, "ok"

    # a minimal valid 1x1 PNG
    PNG_BYTES = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
    )

    def download_file_ssh(ip, password, path):
        return PNG_BYTES

    def run_ssh_cmd(ip, password, cmds):
        run_cmds.append((ip, tuple(cmds)))

    ssh.test_ssh_connection = test_ssh_connection
    ssh.upload_file_ssh = upload_file_ssh
    ssh.download_file_ssh = download_file_ssh
    ssh.run_ssh_cmd = run_ssh_cmd

    # Images stub
    images = ModuleType("src.images")

    def process_image(uploaded_file, width, height):
        return b"processed"

    def get_device_images_dir(device_name):
        return images_dir

    def list_device_images(device_name):
        # return existing files in images_dir
        try:
            return sorted(os.listdir(images_dir))
        except Exception:
            return []

    def save_device_image(device_name, img_data, filename):
        out = os.path.join(images_dir, filename)
        with open(out, "wb") as f:
            f.write(img_data)
        saved_files.append(out)
        return True

    def load_device_image(device_name, img_name):
        p = os.path.join(images_dir, img_name)
        return open(p, "rb").read() if os.path.exists(p) else b""

    def delete_device_image(device_name, img_name):
        p = os.path.join(images_dir, img_name)
        try:
            os.remove(p)
            return True
        except Exception:
            return False

    def rename_device_image(device_name, old, new):
        try:
            os.rename(os.path.join(images_dir, old), os.path.join(images_dir, new))
            return True
        except Exception:
            return False

    images.process_image = process_image
    images.get_device_images_dir = get_device_images_dir
    images.list_device_images = list_device_images
    images.save_device_image = save_device_image
    images.load_device_image = load_device_image
    images.delete_device_image = delete_device_image
    images.rename_device_image = rename_device_image

    # Maintenance stub
    maintenance = ModuleType("src.maintenance")

    def run_maintenance(selected_name, device, base_dir, steps, image, ui):
        maintenance_calls.append((selected_name, device))
        return {"ok": True}

    maintenance.run_maintenance = run_maintenance

    # Dialog stub
    dialog = ModuleType("src.dialog")

    def confirm(title, message, key=None):
        # default to True for tests
        return True

    dialog.confirm = confirm

    # Create a fake package container
    pkg = ModuleType("src")
    pkg.ssh = ssh
    pkg.images = images
    pkg.maintenance = maintenance
    pkg.dialog = dialog

    # Insert into sys.modules
    sys.modules["src"] = pkg
    sys.modules["src.ssh"] = ssh
    sys.modules["src.images"] = images
    sys.modules["src.maintenance"] = maintenance
    sys.modules["src.dialog"] = dialog


def test_upload_and_send_flow(tmp_path):
    # prepare config with one device placed in the repository data/ path
    cfg = {
        "devices": {
            "D1": {"ip": "10.0.0.1", "password": "pw", "device_type": "reMarkable 2"}
        }
    }
    # repository root (project parent of tests/)
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"
    images_dir = data_dir / "images" / "D1"
    # ensure clean test directories
    os.makedirs(images_dir, exist_ok=True)
    # remove any stale images that could contain invalid bytes
    for p in os.listdir(images_dir):
        try:
            os.remove(os.path.join(images_dir, p))
        except Exception:
            pass
    cfg_path = data_dir / "config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    # Register artifact
    art_file = repo_root / ".test_artifacts.json"
    arts = []
    if art_file.exists():
        try:
            arts = json.loads(art_file.read_text(encoding="utf-8"))
        except Exception:
            arts = []
    arts.append(str(cfg_path))
    art_file.write_text(json.dumps(sorted(set(arts))), encoding="utf-8")
    # prepare stubs
    upload_calls = []
    run_cmds = []
    maintenance_calls = []
    saved_files = []
    make_stub_modules(str(images_dir), upload_calls, run_cmds, maintenance_calls, saved_files)

    # ensure config is at expected path relative to BASE_DIR
    # copy data into repo root
    # We'll run AppTest from this repo root by chdir
    at = AppTest.from_file("app.py")
    at.run()

    # Select device
    at.selectbox[0].set_value("D1").run()

    # Instead of using the file_uploader, click the "Importer depuis la tablette" button
    download_btn = None
    for b in at.button:
        if getattr(b, "label", None) == "Importer depuis la tablette":
            download_btn = b
            break
    assert download_btn is not None, "Download button not found"
    download_btn.click().run()

    # download_file_ssh -> save_device_image stub should have recorded a saved file
    assert saved_files, "save_device_image was not called"
    # Register saved files as artifacts
    arts = []
    if art_file.exists():
        try:
            arts = json.loads(art_file.read_text(encoding="utf-8"))
        except Exception:
            arts = []
    arts.extend(saved_files)
    art_file.write_text(json.dumps(sorted(set(arts))), encoding="utf-8")


def test_run_maintenance_flow(tmp_path):
    cfg = {
        "devices": {
            "D1": {"ip": "10.0.0.1", "password": "pw", "device_type": "reMarkable 2", "carousel": True}
        }
    }
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"
    images_dir = data_dir / "images" / "D1"
    os.makedirs(images_dir, exist_ok=True)
    for p in os.listdir(images_dir):
        try:
            os.remove(os.path.join(images_dir, p))
        except Exception:
            pass
    cfg_path = data_dir / "config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    # Register artifact
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    art_file = repo_root / ".test_artifacts.json"
    arts = []
    if art_file.exists():
        try:
            arts = json.loads(art_file.read_text(encoding="utf-8"))
        except Exception:
            arts = []
    arts.append(str(cfg_path))
    art_file.write_text(json.dumps(sorted(set(arts))), encoding="utf-8")

    upload_calls = []
    run_cmds = []
    maintenance_calls = []
    saved_files = []
    make_stub_modules(str(images_dir), upload_calls, run_cmds, maintenance_calls, saved_files)

    at = AppTest.from_file("app.py")
    at.run()
    at.selectbox[0].set_value("D1").run()

    # Click the maintenance button by scanning available buttons
    mbtn = None
    for b in at.button:
        if getattr(b, "label", None) == "Lancer le script complet":
            mbtn = b
            break
    assert mbtn is not None, "Maintenance button not found"
    mbtn.click().run()

    assert maintenance_calls, "run_maintenance was not called"
