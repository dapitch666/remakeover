"""Unit tests for src/maintenance.py — run_maintenance orchestration."""

from contextlib import ExitStack
from unittest.mock import patch

import pytest

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
    dev = Device.from_dict(
        "D1",
        {
            "ip": "1.2.3.4",
            "password": "pw",
            "templates": templates,
            "carousel": carousel,
        },
    )
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
        patch("src.maintenance.remote_templates_dir_has_symlinks", return_value=(True, True)),
        patch("src.maintenance.refresh_templates_backup_from_tablet", return_value=(True, "ok")),
        patch(
            "src.maintenance.upload_file_ssh",
            return_value=(upload_ok, "ok" if upload_ok else "err"),
        ),
        patch("src.maintenance.run_ssh_cmd", return_value=run_cmd_out),
        patch("src.maintenance.sync_templates_to_tablet", return_value=True),
    ]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestRunMaintenanceValidation:
    def test_raises_when_step_fn_is_none(self):
        dev = _device()
        with pytest.raises(ValueError):
            run_maintenance(
                "D1",
                dev,
                step_fn=None,
                progress_fn=lambda p: None,
                toast_fn=lambda m: None,
                log_fn=lambda m: None,
            )

    def test_raises_when_progress_fn_is_none(self):
        dev = _device()
        with pytest.raises(ValueError):
            run_maintenance(
                "D1",
                dev,
                step_fn=lambda m: None,
                progress_fn=None,
                toast_fn=lambda m: None,
                log_fn=lambda m: None,
            )

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
            stack.enter_context(
                patch(
                    "src.maintenance.load_device_image",
                    side_effect=lambda name, img: loaded.append(img) or b"data",
                )
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
                patch(
                    "src.maintenance.load_device_image",
                    side_effect=lambda name, img: loaded.append(img) or b"data",
                )
            )
            run_maintenance("D1", dev, image=None, **_callbacks())

        assert len(loaded) == 1
        assert loaded[0] in ("a.png", "b.png")

    def test_skips_image_step_when_library_empty(self):
        dev = _device()
        upload_calls = []
        patches = _base_patches()
        patches[1] = patch("src.maintenance.list_device_images", return_value=[])
        patches[4] = patch(
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
        sync_calls = []
        with ExitStack() as stack:
            for p in _base_patches():
                stack.enter_context(p)
            stack.enter_context(
                patch(
                    "src.maintenance.sync_templates_to_tablet",
                    side_effect=lambda *args, **kwargs: sync_calls.append((args, kwargs)) or True,
                )
            )
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is True
        assert sync_calls

    def test_with_carousel_enabled(self):
        dev = _device(carousel=True)
        cmd_calls = []
        patches = _base_patches()
        patches[5] = patch(
            "src.maintenance.run_ssh_cmd",
            side_effect=lambda ip, pw, cmds: cmd_calls.append(cmds) or ("", ""),
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
        patches[0] = patch(
            "src.maintenance.load_device_image", side_effect=FileNotFoundError("no file")
        )
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

    def test_list_device_images_exception_treated_as_empty(self):
        """If list_device_images raises, no image step runs and maintenance succeeds."""
        dev = _device()
        patches = _base_patches()
        patches[1] = patch("src.maintenance.list_device_images", side_effect=Exception("io error"))
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image=None, **_callbacks())

        assert result["ok"] is True

    def test_templates_sync_failure_returns_error(self):
        """Unified template sync failure aborts maintenance."""
        dev = _device(templates=True)
        patches = _base_patches()
        patches[6] = patch("src.maintenance.sync_templates_to_tablet", return_value=False)
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is False
        assert any("templates_sync_failed" in e for e in result["errors"])

    def test_carousel_failure_returns_error(self):
        """run_ssh_cmd raising during carousel step aborts maintenance."""
        dev = _device(carousel=True)
        patches = _base_patches()
        patches[5] = patch("src.maintenance.run_ssh_cmd", side_effect=Exception("carousel error"))
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is False
        assert any("carousel_failed" in e for e in result["errors"])

    def test_restart_failure_returns_error(self):
        """run_ssh_cmd raising during xochitl restart aborts maintenance."""
        dev = _device()
        patches = _base_patches()
        patches[5] = patch("src.maintenance.run_ssh_cmd", side_effect=Exception("restart error"))
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = run_maintenance("D1", dev, image="bg.png", **_callbacks())

        assert result["ok"] is False
        assert any("restart_failed" in e for e in result["errors"])

    def test_toast_fn_called_with_success_message(self):
        """toast_fn receives the success message when maintenance completes without errors."""
        dev = _device()
        toasts: list[str] = []
        with ExitStack() as stack:
            for p in _base_patches():
                stack.enter_context(p)
            run_maintenance(
                "D1",
                dev,
                image="bg.png",
                step_fn=lambda m: None,
                progress_fn=lambda p: None,
                toast_fn=toasts.append,
                log_fn=lambda m: None,
            )

        assert any("succès" in t or "success" in t.lower() for t in toasts)

    def test_toast_fn_called_with_error_message_on_failure(self):
        """toast_fn receives the error message on an unexpected exception."""

        def _raise(msg: str) -> None:
            raise RuntimeError("unexpected boom")

        dev = _device()
        toasts: list[str] = []
        with ExitStack() as stack:
            for p in _base_patches():
                stack.enter_context(p)
            run_maintenance(
                "D1",
                dev,
                image="bg.png",
                step_fn=_raise,
                progress_fn=lambda p: None,
                toast_fn=toasts.append,
                log_fn=lambda m: None,
            )

        assert any("erreur" in t.lower() or "error" in t.lower() for t in toasts)
