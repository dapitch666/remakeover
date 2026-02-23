import sys
import os
import shutil
import json
import pytest

# Ensure the repository root is on the import path so `from src import ...` works
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(scope="session", autouse=True)
def clean_test_data():
    """Remove test-created config and images before and after the test session.

    This ensures tests are hermetic and any artifacts created under `data/`
    during tests are removed whether tests pass or fail.
    """
    art_file = os.path.join(ROOT, ".test_artifacts.json")

    def _remove_empty_image_subdirs():
        images_root = os.path.join(ROOT, "data", "images")
        if not os.path.isdir(images_root):
            return
        for name in os.listdir(images_root):
            p = os.path.join(images_root, name)
            try:
                if os.path.isdir(p) and not os.listdir(p):
                    os.rmdir(p)
            except Exception:
                pass

    # Pre-test: if an artifact file exists from a previous run, remove listed artifacts
    if os.path.exists(art_file):
        try:
            with open(art_file, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception:
            items = []
        for p in items:
            try:
                if os.path.isfile(p):
                    os.remove(p)
                elif os.path.isdir(p):
                    shutil.rmtree(p)
            except Exception:
                pass
        try:
            os.remove(art_file)
        except Exception:
            pass

    # Ensure we don't leave empty device dirs from previous runs
    _remove_empty_image_subdirs()

    yield

    # Post-test: remove only artifacts recorded by tests during this session
    if os.path.exists(art_file):
        try:
            with open(art_file, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception:
            items = []
        for p in items:
            try:
                if os.path.isfile(p):
                    os.remove(p)
                elif os.path.isdir(p):
                    shutil.rmtree(p)
            except Exception:
                pass
        try:
            os.remove(art_file)
        except Exception:
            pass
    # Remove any empty per-device image directories left over
    _remove_empty_image_subdirs()
