import os
import io
import shutil
import pytest

import app as rm_app


def test_delete_device_image_removes_file(tmp_path, monkeypatch):
    # Redirect IMAGES_DIR to temporary path
    monkeypatch.setattr(rm_app, "IMAGES_DIR", str(tmp_path / "images"))

    device_name = "Test Device"
    filename = "to_delete.png"
    data = b"PNGDATA"

    # Save file
    saved_path = rm_app.save_device_image(device_name, data, filename)
    assert os.path.exists(saved_path)

    # Delete file
    rm_app.delete_device_image(device_name, filename)
    assert not os.path.exists(saved_path)


def test_delete_device_image_no_error_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(rm_app, "IMAGES_DIR", str(tmp_path / "images2"))
    device_name = "Missing Device"
    filename = "not_there.png"

    # Ensure no exception when deleting non-existent file
    rm_app.delete_device_image(device_name, filename)
