"""Tests for pages/deployment.py.

Covers: empty-config warning, device-selected render, action availability,
full maintenance deploy flow, preferred-image description, random-image description,
and maintenance result display (success / error / reset).
"""

import json
import os
from contextlib import ExitStack
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import (
    PNG_BYTES,
    empty_cfg,
    flow_patches,
    make_env,
    with_device,
    write_config,
)

# ---------------------------------------------------------------------------
# Shared config factory with images in the library
# ---------------------------------------------------------------------------


def _cfg_with_images(tmp_path, preferred: str | None = None) -> str:
    """Config + an image file in the device's images dir."""
    img_dir = tmp_path / "D1" / "images"
    img_dir.mkdir(parents=True)
    (img_dir / "slide.png").write_bytes(b"fake")
    cfg: dict = {
        "devices": {
            "D1": {
                "ip": "10.0.0.1",
                "password": "pw",
                "device_type": "reMarkable 2",
                "carousel": True,
            }
        }
    }
    if preferred:
        cfg["devices"]["D1"]["preferred_image"] = preferred
    return write_config(tmp_path, cfg)


# ---------------------------------------------------------------------------
# Static render checks
# ---------------------------------------------------------------------------


def test_deployment_page_warns_when_no_devices(tmp_path):
    """Deployment page shows 'No device' message with empty config."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deployment.py").run()

    assert not at.exception
    assert any("No device" in m.value for m in at.markdown)


def test_deployment_page_prompts_tablet_selection(tmp_path):
    """With a device configured and selected, deployment page renders info or warning."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deployment.py").run()

    assert not at.exception
    assert at.info or at.warning


def test_deployment_page_shows_info_when_actions_available(tmp_path):
    """Deployment page shows an active deploy button when actions exist."""
    cfg_path = with_device(tmp_path)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deployment.py").run()

    assert not at.exception
    deploy_btn = next((b for b in at.button if "deploy" in b.label.lower()), None)
    assert deploy_btn is not None
    assert not deploy_btn.disabled
    assert not any("aucune action" in w.value.lower() for w in at.warning)


def test_deployment_page_shows_warning_and_disables_button_when_no_actions(tmp_path):
    """When a device has no images, templates=False and carousel=False, deploy is disabled."""
    cfg = {
        "devices": {
            "D1": {
                "ip": "10.0.0.1",
                "password": "pw",
                "device_type": "reMarkable 2",
                "templates": False,
                "carousel": False,
            }
        }
    }
    cfg_path = write_config(tmp_path, cfg)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deployment.py").run()

    assert not at.exception
    assert any(
        "aucune action" in w.value.lower() or "no deployment" in w.value.lower() for w in at.warning
    )
    deploy_btn = next((b for b in at.button if "deploy" in b.label.lower()), None)
    assert deploy_btn is not None
    assert deploy_btn.disabled


def test_deployment_page_shows_warning_when_templates_enabled_but_no_local_files(tmp_path):
    """When templates=True but no local SVG files exist, deploy is still disabled."""
    cfg = {
        "devices": {
            "D1": {
                "ip": "10.0.0.1",
                "password": "pw",
                "device_type": "reMarkable 2",
                "templates": True,
                "carousel": False,
            }
        }
    }
    cfg_path = write_config(tmp_path, cfg)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deployment.py").run()

    assert not at.exception
    assert any(
        "aucune action" in w.value.lower() or "no deployment" in w.value.lower() for w in at.warning
    )
    deploy_btn = next((b for b in at.button if "deploy" in b.label.lower()), None)
    assert deploy_btn is not None
    assert deploy_btn.disabled


# ---------------------------------------------------------------------------
# Full maintenance flow
# ---------------------------------------------------------------------------


def test_run_maintenance_flow(tmp_path):
    """Clicking 'Deploy configuration' triggers run_maintenance."""
    cfg = {
        "devices": {
            "D1": {
                "ip": "10.0.0.1",
                "password": "pw",
                "device_type": "reMarkable 2",
                "carousel": True,
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
    maintenance_calls: list = []

    patches = flow_patches(images_dir, upload_calls, run_cmds, saved_files)
    # Replace the generic maintenance patch with one that records calls
    patches[11] = patch(
        "src.maintenance.run_maintenance",
        side_effect=lambda name,
        dev,
        image=None,
        step_fn=None,
        progress_fn=None,
        toast_fn=None,
        log_fn=None: maintenance_calls.append((name, dev)) or {"ok": True},
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch.dict(
                os.environ,
                {"RM_CONFIG_PATH": str(cfg_file), "RM_DATA_DIR": str(tmp_path)},
            )
        )
        for p in patches:
            stack.enter_context(p)

        at = AppTest.from_file("app.py")
        at.run()
        at.sidebar.selectbox[0].set_value("D1").run()
        at.switch_page("pages/deployment.py").run()

        mbtn = next(
            (b for b in at.button if getattr(b, "label", None) == "Deploy configuration"),
            None,
        )
        assert mbtn is not None, "Maintenance button not found"
        mbtn.click().run()

    assert maintenance_calls, "run_maintenance was not called"


# ---------------------------------------------------------------------------
# Description block — preferred image / random image branches
# ---------------------------------------------------------------------------


def test_preferred_image_shown_in_description(tmp_path):
    """When a preferred image is configured, its name appears in the description."""
    cfg_path = _cfg_with_images(tmp_path, preferred="slide.png")
    env = make_env(tmp_path, cfg_path)
    with (
        patch.dict(os.environ, env),
        patch("src.images.list_device_images", return_value=["slide.png"]),
        patch("src.images.load_device_image", return_value=PNG_BYTES),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deployment.py").run()

    assert not at.exception
    all_text = " ".join(m.value for m in at.info)
    assert "slide.png" in all_text


def test_random_image_shown_in_description(tmp_path):
    """When no preferred image is set but images exist, a random one is chosen."""
    cfg_path = _cfg_with_images(tmp_path, preferred=None)
    env = make_env(tmp_path, cfg_path)
    with (
        patch.dict(os.environ, env),
        patch("src.images.list_device_images", return_value=["slide.png"]),
        patch("src.images.load_device_image", return_value=PNG_BYTES),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deployment.py").run()

    assert not at.exception
    all_text = " ".join(m.value for m in at.info)
    assert "random" in all_text or "slide.png" in all_text


# ---------------------------------------------------------------------------
# Maintenance result display
# ---------------------------------------------------------------------------


def test_maintenance_result_success_display(tmp_path):
    """Pre-setting a successful maint_result shows the success banner."""
    cfg_path = with_device(tmp_path)
    env = make_env(tmp_path, cfg_path)
    with patch.dict(os.environ, env):
        at = AppTest.from_file("app.py")
        at.run()
        at.session_state["maint_result_D1"] = {"ok": True, "errors": [], "details": {}}
        at.switch_page("pages/deployment.py").run()

    assert not at.exception
    assert at.success


def test_maintenance_result_error_display(tmp_path):
    """Pre-setting a failed maint_result shows the error banner with the error list."""
    cfg_path = with_device(tmp_path)
    env = make_env(tmp_path, cfg_path)
    with patch.dict(os.environ, env):
        at = AppTest.from_file("app.py")
        at.run()
        at.session_state["maint_result_D1"] = {
            "ok": False,
            "errors": ["restart_failed: timeout"],
            "details": {},
        }
        at.switch_page("pages/deployment.py").run()

    assert not at.exception
    assert at.error
    assert any("restart_failed" in m.value for m in at.markdown)


def test_maintenance_reset_button_clears_result(tmp_path):
    """Clicking the Reset button removes maint_result from session state."""
    cfg_path = with_device(tmp_path)
    env = make_env(tmp_path, cfg_path)
    with patch.dict(os.environ, env):
        at = AppTest.from_file("app.py")
        at.run()
        at.session_state["maint_result_D1"] = {"ok": True, "errors": [], "details": {}}
        at.switch_page("pages/deployment.py").run()
        reset_btn = next((b for b in at.button if "reset" in b.label.lower()), None)
        assert reset_btn is not None
        reset_btn.click().run()

    assert not at.exception
    assert "maint_result_D1" not in at.session_state
