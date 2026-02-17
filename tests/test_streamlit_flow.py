import importlib
import json
import os
import shutil
import sys

import pytest


class FakeColumn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSidebar:
    def radio(self, *args, **kwargs):
        # Force configuration page
        return ":material/settings: Configuration"


class StreamlitRerun(Exception):
    pass


class FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self._clicks = []
        self.sidebar = FakeSidebar()

    def set_clicks(self, clicks):
        self._clicks = clicks

    def set_page_config(self, *a, **k):
        pass

    def logo(self, *a, **k):
        pass

    def title(self, *a, **k):
        pass

    def subheader(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def toast(self, *a, **k):
        pass

    def stop(self):
        raise StreamlitRerun()

    def rerun(self):
        raise StreamlitRerun()

    def divider(self):
        pass

    def write(self, *a, **k):
        pass

    def markdown(self, *a, **k):
        pass

    def image(self, *a, **k):
        pass

    def selectbox(self, label, options, **kwargs):
        # If the first option is a placeholder like "-- Create... --", return the next
        if options and isinstance(options, (list, tuple)):
            first = options[0]
            if isinstance(first, str) and first.startswith("--") and len(options) > 1:
                return options[1]
            return options[0]
        return None

    def text_input(self, *a, **k):
        return k.get('value', '') if 'value' in k else ''

    def checkbox(self, *a, **k):
        return k.get('value', False)

    def columns(self, n, **k):
        # Accept either integer or a sequence of column ratios
        if isinstance(n, int):
            count = n
        else:
            try:
                count = len(n)
            except Exception:
                count = 1
        return [FakeColumn() for _ in range(count)]

    def button(self, label, key=None, **kwargs):
        identifier = key if key else label
        return identifier in self._clicks

    def file_uploader(self, *a, **k):
        return None

    def __getattr__(self, item):
        # fallback no-op for other attributes
        def _noop(*a, **k):
            return None

        return _noop


@pytest.mark.usefixtures("tmp_path")
def test_streamlit_delete_device_flow(tmp_path, monkeypatch):
    repo_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    data_dir = os.path.join(repo_root, "data")
    cfg_path = os.path.join(data_dir, "config.json")

    # Backup original config
    backup_cfg = None
    if os.path.exists(cfg_path):
        backup_cfg = tmp_path / "config_backup.json"
        shutil.copy(cfg_path, str(backup_cfg))

    test_device = "DeviceForTest"
    # Create a temporary config with a single test device
    test_config = {
        "devices": {
            test_device: {
                "ip": "127.0.0.1",
                "password": "",
                "device_type": "reMarkable Paper Pro",
                "templates": False,
                "carousel": True,
            }
        }
    }

    os.makedirs(data_dir, exist_ok=True)
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(test_config, f)

    # Create an image file for the device
    images_dir = os.path.join(repo_root, "data", "images", test_device.replace("/", "_").replace(" ", "_"))
    os.makedirs(images_dir, exist_ok=True)
    img_path = os.path.join(images_dir, "todelete.png")
    with open(img_path, 'wb') as f:
        f.write(b"PNG")
    assert os.path.exists(img_path)

    # Prepare fake streamlit and install it into sys.modules
    fake_st = FakeStreamlit()
    monkeypatch.setitem(sys.modules, 'streamlit', fake_st)

    # First run: simulate clicking the main "Supprimer" button in Configuration
    fake_st.set_clicks(["Supprimer"])

    # Ensure app is not in sys.modules to force fresh import
    if 'app' in sys.modules:
        del sys.modules['app']

    # Import app and expect a rerun when delete is initiated
    with pytest.raises(StreamlitRerun):
        importlib.import_module('app')

    # Now simulate clicking the confirm button
    fake_st.set_clicks([f"confirm_delete_{test_device}"])

    # Import app again to process the confirmation
    if 'app' in sys.modules:
        del sys.modules['app']
    with pytest.raises(StreamlitRerun):
        importlib.import_module('app')

    # After confirmation, device should be removed from config and images deleted
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    assert test_device not in cfg.get('devices', {})
    assert not os.path.exists(images_dir)

    # Cleanup: restore original config
    if backup_cfg:
        shutil.copy(str(backup_cfg), cfg_path)
    else:
        os.remove(cfg_path)
