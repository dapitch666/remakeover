"""Unit tests for src/ui_common.py — Streamlit-free logic."""

from unittest.mock import patch

from src.models import Device
from src.ui_common import normalise_filename, send_suspended_png


class TestNormaliseFilename:
    # ── spaces ───────────────────────────────────────────────────────────

    def test_spaces_are_preserved(self):
        assert normalise_filename("my file.png") == "my file.png"

    def test_already_normalised_unchanged(self):
        assert normalise_filename("my_file.png") == "my_file.png"

    # ── extension handling (default .png) ────────────────────────────────

    def test_correct_extension_already_present(self):
        assert normalise_filename("photo.png") == "photo.png"

    def test_extension_is_case_insensitive(self):
        assert normalise_filename("photo.PNG") == "photo.PNG"

    def test_known_extension_swapped(self):
        result = normalise_filename("photo.jpg")
        assert result == "photo.png"

    def test_unknown_dot_in_name_preserved(self):
        """Dots inside a base name (e.g. 'alice.et.merlin') must not be stripped."""
        result = normalise_filename("alice.et.merlin")
        assert result == "alice.et.merlin.png"

    def test_no_extension_appended(self):
        assert normalise_filename("photo") == "photo.png"

    # ── custom extension ─────────────────────────────────────────────────

    def test_svg_extension(self):
        assert normalise_filename("icon", ext=".svg") == "icon.svg"

    def test_svg_already_present(self):
        assert normalise_filename("icon.svg", ext=".svg") == "icon.svg"

    def test_known_extension_swapped_to_svg(self):
        assert normalise_filename("icon.png", ext=".svg") == "icon.svg"


# ---------------------------------------------------------------------------
# send_suspended_png
# ---------------------------------------------------------------------------


class TestSendSuspendedPng:
    _device = Device.from_dict("D1", {"ip": "10.0.0.1", "password": "pw"})

    def test_success_returns_true_and_logs(self):
        log: list[str] = []
        with (
            patch("src.ui_common._ssh.upload_file_ssh", return_value=(True, "ok")),
            patch("src.ui_common._ssh.run_ssh_cmd"),
        ):
            result = send_suspended_png(self._device, b"imgdata", "bg.png", "D1", log.append)
        assert result is True
        assert any("Sent" in m for m in log)

    def test_failure_returns_false_and_logs_error(self):
        log: list[str] = []
        with patch("src.ui_common._ssh.upload_file_ssh", return_value=(False, "refused")):
            result = send_suspended_png(self._device, b"imgdata", "bg.png", "D1", log.append)
        assert result is False
        assert any("Error" in m for m in log)
