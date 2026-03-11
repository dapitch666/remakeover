"""Local image management helpers used by the UI and maintenance logic.

All images are stored as PNG files under ``data/{device}/images/``.
"""

import io
import logging
import os
from contextlib import suppress

from PIL import Image

from src.config import get_device_data_dir

logger = logging.getLogger(__name__)


def get_device_images_dir(device_name: str) -> str:
    """Return (and create) the per-device images directory: ``data/{device}/images/``."""
    device_dir = os.path.join(get_device_data_dir(device_name), "images")
    os.makedirs(device_dir, exist_ok=True)
    return device_dir


def list_device_images(device_name: str) -> list[str]:
    """Return PNG filenames in the device image directory, sorted by modification time (newest first)."""
    device_dir = get_device_images_dir(device_name)
    files = [f for f in os.listdir(device_dir) if f.endswith(".png")]
    return sorted(files, key=lambda f: os.path.getmtime(os.path.join(device_dir, f)), reverse=True)


def save_device_image(device_name: str, image_data: bytes, filename: str) -> str:
    """Write *image_data* to ``{images_dir}/{filename}`` and return the full path."""
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "wb") as f:
        f.write(image_data)
    return filepath


def load_device_image(device_name: str, filename: str) -> bytes:
    """Read and return the raw bytes of ``{images_dir}/{filename}``."""
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "rb") as f:
        return f.read()


def delete_device_image(device_name: str, filename: str) -> None:
    """Delete ``{images_dir}/{filename}`` if it exists."""
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


def rename_device_image(device_name: str, old_filename: str, new_filename: str) -> bool:
    """Rename an image file; returns True on success, False if the source does not exist."""
    device_dir = get_device_images_dir(device_name)
    old_path = os.path.join(device_dir, old_filename)
    new_path = os.path.join(device_dir, new_filename)
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        return True
    return False


def process_image(uploaded_file, width: int, height: int) -> bytes:
    """Resize and convert *uploaded_file* to a PNG of exactly *width* × *height* pixels.

    If the file is already a PNG at the target size it is returned as-is.
    """
    img = Image.open(uploaded_file)
    if img.format == "PNG" and img.size == (width, height):
        with suppress(Exception):
            uploaded_file.seek(0)
        return uploaded_file.read()
    result = img.resize((width, height), Image.Resampling.LANCZOS).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()
