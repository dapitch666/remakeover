"""Deployment page."""

import random
from contextlib import suppress

import streamlit as st

import src.images as _images
import src.maintenance as _maint
from src.i18n import _
from src.models import Device
from src.templates import list_device_templates
from src.ui_common import deferred_toast, rainbow_divider, require_device


def _localize_maintenance_error(err: str) -> str:
    """Return a localized user-facing message for a maintenance error code."""
    prefix, _sep, detail = err.partition(":")
    labels = {
        "load_image_failed": _("Failed to load local image"),
        "upload_suspended_failed": _("Failed to upload suspended image"),
        "ensure_remote_dirs_failed": _("Failed to prepare template directories on tablet"),
        "symlink_failed": _("Failed to create template links on tablet"),
        "templates_json_error": _("Error while syncing templates.json"),
        "templates_sync_failed": _("Error while syncing templates.json"),
        "carousel_failed": _("Failed to disable carousel"),
        "restart_failed": _("Failed to restart xochitl"),
    }
    if prefix not in labels:
        return err
    detail = detail.strip()
    if detail:
        return _("{label}: {detail}").format(label=labels[prefix], detail=detail)
    return labels[prefix]


st.title(_(":material/rocket_launch: Deployment"))
rainbow_divider()

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)
selected_name = st.session_state.get("selected_name")

DEVICES = config.get("devices", {})

require_device(DEVICES, selected_name)
assert isinstance(selected_name, str)

device = Device.from_dict(selected_name, DEVICES[selected_name])

st.markdown(
    _(
        "After each firmware update, the tablet's customisations "
        "(suspended image, templates, carousel) are reset by the system. "
        "This page lets you **redeploy your local configuration** to the device in one operation."
    )
)
st.divider()

imgs_available = _images.list_device_images(selected_name)

# Resolve the image that will be uploaded
image: str | None
choice: str | None
if device.preferred_image:
    image = device.preferred_image
    choice = "preferred"
elif imgs_available:
    image = random.choice(imgs_available)
    choice = "random"
else:
    image = None
    choice = None

# ── Description block ────────────────────────────────────────────────
lines = [_("**The deployment will perform the following operations:**")]
if choice == "preferred":
    lines.append(
        _(
            "- Send the preferred image (`{image}`) as the suspended image (`suspended.png`) to the tablet"
        ).format(image=image)
    )
elif choice == "random":
    lines.append(
        _(
            "- Send `{image}` (random choice, no preferred image) as the suspended image (`suspended.png`) to the tablet"
        ).format(image=image)
    )
else:
    lines.append(_("- *(No local image — suspended image upload skipped)*"))
if device.templates and bool(list_device_templates(selected_name)):
    lines.append(
        _(
            "- Create symbolic links to the custom templates and update `templates.json` on the tablet"
        )
    )
if device.carousel:
    lines.append(_("- Disable the carousel by moving illustrations to a backup folder"))
lines.append(_("- Restart `xochitl` to apply changes"))

templates_active = device.templates and bool(list_device_templates(selected_name))
has_meaningful_actions = bool(image) or templates_active or device.carousel

if has_meaningful_actions:
    st.info("\n".join(lines))
else:
    st.warning(
        _(
            "No deployment actions configured for this tablet "
            "(no local image, templates disabled or empty, carousel disabled). "
            "Deployment would only restart `xochitl`."
        ),
        icon=":material/warning:",
    )

# ── Run / result state ───────────────────────────────────────────────
result_key = f"maint_result_{selected_name}"
result = st.session_state.get(result_key)

if result is not None:
    if result.get("ok"):
        st.success(_("Deployment completed successfully."), icon=":material/task_alt:")
    else:
        st.error(_("Deployment completed with errors:"), icon=":material/error:")
        for e in result.get("errors", []):
            local_e = _localize_maintenance_error(e)
            if local_e == e:
                st.markdown(f"- `{e}`")
            else:
                st.markdown(f"- `{e}` - {local_e}")
    if st.button(
        _("Reset"),
        key=f"maint_reset_{selected_name}",
        icon=":material/refresh:",
    ):
        del st.session_state[result_key]
        st.rerun()
else:
    # ── Launch button ────────────────────────────────────────────────────
    _left, col, _right = st.columns([1, 3, 1])
    with col:
        if st.button(
            _("Deploy configuration"),
            key=f"ui_launch_maintenance_{selected_name}",
            icon=":material/autorenew:",
            help=_("Redeploy your local configuration to the tablet after a firmware update"),
            type="primary",
            width="stretch",
            disabled=not has_meaningful_actions,
        ):
            with st.status(_("Deploying…"), expanded=True) as status:
                progress = st.progress(0)

                def _step(msg: str) -> None:
                    with suppress(Exception):
                        status.text(msg)

                result = _maint.run_maintenance(
                    selected_name,
                    device,
                    image,
                    step_fn=_step,
                    progress_fn=lambda pct: progress.progress(pct),
                    toast_fn=lambda msg: deferred_toast(msg, ":material/task_alt:"),
                    log_fn=add_log,
                )

            st.session_state[result_key] = result
            st.rerun()
