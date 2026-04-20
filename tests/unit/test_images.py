"""Unit tests for src/images.py — local image management helpers."""

import io
import os
from unittest.mock import patch

import pytest
from PIL import Image

import src.images as images_mod
from src.models import Device


@pytest.fixture(autouse=True)
def _patch_data_dir(tmp_path, monkeypatch):
    """Redirect get_device_data_dir to tmp_path so no real data/ is touched."""
    monkeypatch.setattr(images_mod, "get_device_data_dir", lambda name: str(tmp_path / name))


DEVICE = "TestDevice"
PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd5N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_png_bytes(width: int, height: int, color=(200, 100, 50)) -> bytes:
    """Return in-memory PNG bytes at the given dimensions."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# list_device_images
# ---------------------------------------------------------------------------


class TestListDeviceImages:
    def test_empty_dir_returns_empty_list(self):
        assert images_mod.list_device_images(DEVICE) == []

    def test_returns_only_png_files(self):
        images_mod.save_device_image(DEVICE, PNG_1PX, "photo.png")
        images_mod.save_device_image(DEVICE, b"data", "readme.txt")
        result = images_mod.list_device_images(DEVICE)
        assert result == ["photo.png"]
        assert "readme.txt" not in result

    def test_sorted_by_mtime_newest_first(self):
        images_mod.save_device_image(DEVICE, PNG_1PX, "old.png")
        images_mod.save_device_image(DEVICE, PNG_1PX, "new.png")
        d = images_mod.get_device_images_dir(DEVICE)
        os.utime(os.path.join(d, "old.png"), (1000, 1000))
        os.utime(os.path.join(d, "new.png"), (2000, 2000))
        result = images_mod.list_device_images(DEVICE)
        assert result[0] == "new.png"
        assert result[1] == "old.png"


# ---------------------------------------------------------------------------
# save_device_image / load_device_image
# ---------------------------------------------------------------------------


class TestSaveLoadImage:
    def test_roundtrip(self):
        images_mod.save_device_image(DEVICE, PNG_1PX, "img.png")
        assert images_mod.load_device_image(DEVICE, "img.png") == PNG_1PX

    def test_save_returns_filepath(self):
        path = images_mod.save_device_image(DEVICE, PNG_1PX, "img.png")
        assert os.path.exists(path)
        assert path.endswith("img.png")

    def test_load_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            images_mod.load_device_image(DEVICE, "ghost.png")


# ---------------------------------------------------------------------------
# delete_device_image
# ---------------------------------------------------------------------------


class TestDeleteDeviceImage:
    def test_existing_file_is_removed(self):
        images_mod.save_device_image(DEVICE, PNG_1PX, "bye.png")
        images_mod.delete_device_image(DEVICE, "bye.png")
        assert images_mod.list_device_images(DEVICE) == []

    def test_missing_file_is_noop(self):
        images_mod.delete_device_image(DEVICE, "ghost.png")  # must not raise


# ---------------------------------------------------------------------------
# rename_device_image
# ---------------------------------------------------------------------------


class TestRenameDeviceImage:
    def test_success(self):
        images_mod.save_device_image(DEVICE, PNG_1PX, "before.png")
        result = images_mod.rename_device_image(DEVICE, "before.png", "after.png")
        assert result is True
        assert "after.png" in images_mod.list_device_images(DEVICE)
        assert "before.png" not in images_mod.list_device_images(DEVICE)

    def test_missing_source_returns_false(self):
        assert images_mod.rename_device_image(DEVICE, "ghost.png", "new.png") is False


# ---------------------------------------------------------------------------
# process_image
# ---------------------------------------------------------------------------


class TestProcessImage:
    def test_already_correct_size_returns_original_bytes(self):
        target_w, target_h = 100, 100
        raw = _make_png_bytes(target_w, target_h)
        result = images_mod.process_image(io.BytesIO(raw), target_w, target_h)
        assert result == raw

    def test_different_size_is_resized(self):
        raw = _make_png_bytes(50, 50)
        result = images_mod.process_image(io.BytesIO(raw), 100, 200)
        out_img = Image.open(io.BytesIO(result))
        assert out_img.size == (100, 200)

    def test_jpeg_is_converted_to_png(self):
        img = Image.new("RGB", (10, 10), (0, 255, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        result = images_mod.process_image(buf, 10, 10)
        out_img = Image.open(io.BytesIO(result))
        assert out_img.format == "PNG"

    def test_rgba_image_is_converted_to_rgb_png(self):
        """RGBA input at a *different* size is resized and converted to RGB."""
        img = Image.new("RGBA", (8, 8), (255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        result = images_mod.process_image(buf, 16, 16)
        out_img = Image.open(io.BytesIO(result))
        assert out_img.mode == "RGB"
        assert out_img.size == (16, 16)


# ---------------------------------------------------------------------------
# send_suspended_png
# ---------------------------------------------------------------------------


class TestSendSuspendedPng:
    _device = Device.from_dict("D1", {"ip": "10.0.0.1", "password": "pw"})

    def test_success_first_send_restarts_xochitl(self):
        """First send: SleepScreenPath is newly written, so xochitl is restarted."""
        log: list[str] = []
        run_calls: list = []
        # First run_ssh_cmd call is _ensure_sleep_screen_path → returns 'just_set'
        # Second call is CMD_RESTART_XOCHITL
        responses = [("just_set", ""), ("", "")]

        def _run_cmd(_device, cmds):
            run_calls.append(cmds)
            return responses.pop(0)

        with (
            patch("src.images._ssh.upload_file_ssh", return_value=(True, "ok")),
            patch("src.images._ssh.run_ssh_cmd", side_effect=_run_cmd),
        ):
            result = images_mod.send_suspended_png(self._device, b"imgdata", "bg.png", log.append)
        assert result is True
        assert any("Sent" in m for m in log)
        assert len(run_calls) == 2

    def test_success_subsequent_send_skips_restart(self):
        """Subsequent send: SleepScreenPath already set, xochitl is NOT restarted."""
        log: list[str] = []
        run_calls: list = []

        def _run_cmd(_device, cmds):
            run_calls.append(cmds)
            return "already_set", ""

        with (
            patch("src.images._ssh.upload_file_ssh", return_value=(True, "ok")),
            patch("src.images._ssh.run_ssh_cmd", side_effect=_run_cmd),
        ):
            result = images_mod.send_suspended_png(self._device, b"imgdata", "bg.png", log.append)
        assert result is True
        assert any("Sent" in m for m in log)
        assert len(run_calls) == 1  # only the ensure call, no restart

    def test_failure_returns_false_and_logs_error(self):
        log: list[str] = []
        with patch("src.images._ssh.upload_file_ssh", return_value=(False, "refused")):
            result = images_mod.send_suspended_png(self._device, b"imgdata", "bg.png", log.append)
        assert result is False
        assert any("Error" in m for m in log)


# ---------------------------------------------------------------------------
# rollback_sleep_screen
# ---------------------------------------------------------------------------


class TestRollbackSleepScreen:
    _device = Device.from_dict("D1", {"ip": "10.0.0.1", "password": "pw"})

    def test_success_returns_true_and_logs(self):
        log: list[str] = []
        with patch("src.images._ssh.run_ssh_cmd", return_value=("", "")):
            result = images_mod.rollback_sleep_screen(self._device, log.append)
        assert result is True
        assert any("reset" in m for m in log)

    def test_failure_returns_false_and_logs_error(self):
        log: list[str] = []
        with patch("src.images._ssh.run_ssh_cmd", return_value=("", "Connection refused")):
            result = images_mod.rollback_sleep_screen(self._device, log.append)
        assert result is False
        assert any("Error" in m for m in log)
