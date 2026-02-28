"""Unit tests for src.maintenance.run_maintenance."""

import pytest
from contextlib import ExitStack
from unittest.mock import patch, MagicMock

from src.maintenance import run_maintenance
from src.models import Device


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _callbacks():
    """Return keyword callables for step_fn, progress_fn, toast_fn, log_fn."""
    return dict(
        step_fn=lambda msg: None,
        progress_fn=lambda pct: None,
        toast_fn=lambda msg: None,
        log_fn=lambda msg: None,
    )


def _device(templates=False, carousel=False, preferred_image=None):
    dev = Device.from_dict("D1", {
        "ip": "1.2.3.4",
        "password": "pw",
        "templates": templates,
        "carousel": carousel,
    })
    dev.preferred_image = preferred_image
    return dev


def _base_patches(
    load_image_data=b"imgdata",
    upload_ok=True,
    run_cmd_out=("", ""),
):
    """Return list of patch context managers covering all side-effectful calls."""
    return [
        patch("src.maintenance.load_device_image", return_value=load_image_data),
        patch("src.maintenance.list_device_images", return_value=[]),
        patch("src.maintenance.upload_file_ssh",
              return_value=(upload_ok, "ok" if upload_ok else "err")),
        patch("src.maintenance.run_ssh_cmd", return_value=run_cmd_out),
        patch("src.maintenance.ensure_remote_template_dirs", return_value=(True, "ok")),
        patch("src.maintenance.upload_template_svgs", return_value=0),
        patch("src.maintenance.compare_and_backup_templates_json", return_value=(True, "identical")),
        patch("src.maintenance.get_device_templates_dir", return_value="/tmp/tpl"),
    ]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestRunMaintenanceValidation:
    def test_raises_when_step_fn_is_none(self):
        dev = _device()
        with pytest.raises(ValueError):
            run_maintenance("D1", dev, step_fn=None, progress_fn=lambda p: None,
                            toast_fn=lambda m: None, log_fn=lambda m: None)

    def test_raises_when_progress_fn_is_none(self):
        dev = _device()
        with pytest.raises(ValueError):
            run_maintenance("D1", dev, step_fn=lambda m: None, progress_fn=None,
                            toast_fn=lambda m: None, log_fn=lambda m: None)

    def test_raises_when_no_callbacks(self):
        dev = _device()
        with pytest.raises(ValueError):
            run_maintenance("D1", dev)


# ---------------------------------------------------------------------------
# Image resolution (no explicit image argument)
# ---------------------------------------------------------------------------

class TestImageResolution:
    def test_uses_preferred_image_when_set(self):
        dev = _device(preferred_image="my.png")
        loaded = []
        with ExitStack() as stack:
            for p in _base_patches():
                stack.enter_context(p)
            mock_load = stack.enter_context(
                patch("src.maintenance.load_device_image",
                      side_effect=lambda name, img: loaded.append(img) or b"data")
            )
            run_maintenance("D1", dev, image=None, **_callbacks())

        assert "my.png" in loaded

    def test_picks_library_image_when_no_preferred(self):
        dev = _device()
        loaded = []
        patches = _base_patches()
        patches[1] = patch("src.maintenance.list_device_images", return_value=["a.png", "b.png"])
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(
                patch("src.maintenance.load_device_image",
                      side_effect=lambda name, img: loaded.append(img) or b"data")
            )
            run_maintenance("D1", dev, image=None, **_callbacks())

        assert len(loaded) == 1
        assert loaded[0] in ("a.png", "b.png")

    def test_skips_image_step_when_library_empty(self):
        dev = _device()
        upload_calls = []
        patches = _base_patches()
        patches[1] = patch("src.maintenance.list_device_images", return_value=[])
        patches[2] = patch(
            "src.maintenance.upload_file_ssh",
            side_effect=lambda ip, pw, blob, path: upload_calls.append(path) or (True, "ok"),
        )
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image=None, **_callbacks())

        assert result["ok"] is True
        assert upload_calls == []  # no image upload triggered


# ---------------------------------------------------------------------------
# Happy-path outcomes
# ---------------------------------------------------------------------------

class TestRunMaintenanceHappyPath:
    def test_image_upload_only(self):
        dev = _device()
        with ExitStack() as stack:
            for p in _base_patches():
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is True
        assert result["errors"] == []

    def test_with_templates_enabled(self):
        dev = _device(templates=True)
        ensure_calls = []
        with ExitStack() as stack:
            for p in _base_patches():
                stack.enter_context(p)
            stack.enter_context(
                patch("src.maintenance.ensure_remote_template_dirs",
                      side_effect=lambda ip, pw, c, t: ensure_calls.append((c, t)) or (True, "ok"))
            )
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is True
        assert ensure_calls  # template dirs were set up

    def test_with_carousel_enabled(self):
        dev = _device(carousel=True)
        cmd_calls = []
        patches = _base_patches()
        patches[3] = patch(
            "src.maintenance.run_ssh_cmd",
            side_effect=lambda ip, pw, cmds: cmd_calls.append(cmds) or ("", "")
        )
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is True
        # At minimum the carousel backup command and xochitl restart command ran
        all_cmds = [cmd for cmds in cmd_calls for cmd in cmds]
        assert any("xochitl" in c for c in all_cmds)

    def test_full_maintenance(self):
        dev = _device(templates=True, carousel=True)
        with ExitStack() as stack:
            for p in _base_patches():
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is True


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

class TestRunMaintenanceErrors:
    def test_image_load_failure_returns_error(self):
        dev = _device()
        patches = _base_patches()
        patches[0] = patch("src.maintenance.load_device_image",
                           side_effect=FileNotFoundError("no file"))
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="missing.png", **_callbacks())

        assert result["ok"] is False
        assert any("load_image_failed" in e for e in result["errors"])

    def test_image_upload_failure_returns_error(self):
        dev = _device()
        patches = _base_patches(upload_ok=False)
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is False
        assert any("upload_suspended_failed" in e for e in result["errors"])

    def test_ensure_remote_dirs_failure_returns_error(self):
        dev = _device(templates=True)
        patches = _base_patches()
        patches[4] = patch("src.maintenance.ensure_remote_template_dirs",
                           return_value=(False, "permission denied"))
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is False
        assert any("ensure_remote_dirs_failed" in e for e in result["errors"])

    def test_symlink_failure_returns_error(self):
        dev = _device(templates=True)
        patches = _base_patches()
        # send_count > 0 so symlink command is attempted
        patches[5] = patch("src.maintenance.upload_template_svgs", return_value=1)
        patches[3] = patch("src.maintenance.run_ssh_cmd",
                           side_effect=Exception("bash error"))
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is False
        assert any("symlink_failed" in e for e in result["errors"])

    def test_restart_failure_returns_error(self):
        dev = _device()
        patches = _base_patches()
        patches[3] = patch("src.maintenance.run_ssh_cmd",
                           side_effect=Exception("connection lost"))
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is False
        assert any("restart_failed" in e for e in result["errors"])
