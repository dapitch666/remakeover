"""Image utilities scaffold.

Provide local image management helpers used by the UI and maintenance
logic. Intended API mirrors the functions currently inside `app.py`.
"""

import io
import logging
import os
from contextlib import suppress

from PIL import Image

from src.config import get_device_data_dir

logger = logging.getLogger(__name__)


def get_device_images_dir(device_name: str) -> str:
    device_dir = os.path.join(get_device_data_dir(device_name), "images")
    os.makedirs(device_dir, exist_ok=True)
    return device_dir


def list_device_images(device_name: str) -> list[str]:
    device_dir = get_device_images_dir(device_name)
    files = [f for f in os.listdir(device_dir) if f.endswith(".png")]
    return sorted(files, key=lambda f: os.path.getmtime(os.path.join(device_dir, f)), reverse=True)


def save_device_image(device_name: str, image_data: bytes, filename: str) -> str:
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "wb") as f:
        f.write(image_data)
    return filepath


def load_device_image(device_name: str, filename: str) -> bytes:
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "rb") as f:
        return f.read()


def delete_device_image(device_name: str, filename: str) -> None:
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


def rename_device_image(device_name: str, old_filename: str, new_filename: str) -> bool:
    device_dir = get_device_images_dir(device_name)
    old_path = os.path.join(device_dir, old_filename)
    new_path = os.path.join(device_dir, new_filename)
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        return True
    return False


def process_image(uploaded_file, width: int, height: int) -> bytes:
    img = Image.open(uploaded_file)
    if img.format == "PNG" and img.size == (width, height):
        with suppress(Exception):
            uploaded_file.seek(0)
        return uploaded_file.read()
    result = img.resize((width, height), Image.Resampling.LANCZOS).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()
