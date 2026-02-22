import os
import types

import pytest


class DummyUI:
    def __init__(self):
        self.steps = []
        self.progress_vals = []
        self.toasts = []

    def step(self, msg: str):
        self.steps.append(msg)

    def progress(self, pct: int):
        self.progress_vals.append(pct)

    def toast(self, msg: str):
        self.toasts.append(msg)


def test_run_maintenance_success(monkeypatch, tmp_path):
    # Prepare device config
    device = {'ip': '1.2.3.4', 'password': 'pw', 'templates': True, 'carousel': True}

    # Monkeypatch external calls used by run_maintenance
    monkeypatch.setattr('src.maintenance.upload_file_ssh', lambda ip, pw, content, path: (True, 'OK'))
    monkeypatch.setattr('src.maintenance.ensure_remote_template_dirs', lambda ip, pw, a, b: (True, 'ok'))
    monkeypatch.setattr('src.maintenance.upload_template_svgs', lambda ip, pw, dirs, remote: 1)
    monkeypatch.setattr('src.maintenance.backup_and_replace_templates_json', lambda ip, pw, local_path, remote_dir, base_dir: (True, 'OK'))
    monkeypatch.setattr('src.maintenance.list_device_images', lambda name: [])
    monkeypatch.setattr('src.maintenance.load_device_image', lambda name, fname: b'img')
    def fake_run_ssh_cmd(ip, pw, cmds):
        return ("ok", "")

    monkeypatch.setattr('src.maintenance.run_ssh_cmd', fake_run_ssh_cmd)

    ui = DummyUI()
    from src.maintenance import run_maintenance

    result = run_maintenance('dev', device, str(tmp_path), None, ui)
    assert result.get('ok') is True
    assert ui.toasts and 'Maintenance' in ui.toasts[-1]


def test_run_maintenance_upload_failure(monkeypatch, tmp_path):
    device = {'ip': '1.2.3.4', 'password': 'pw', 'templates': True, 'carousel': True}

    # Monkeypatch external calls used by run_maintenance
    # Simulate upload failure for suspended.png
    monkeypatch.setattr('src.maintenance.upload_file_ssh', lambda ip, pw, content, path: (False, 'err'))
    monkeypatch.setattr('src.maintenance.ensure_remote_template_dirs', lambda ip, pw, a, b: (True, 'ok'))
    monkeypatch.setattr('src.maintenance.upload_template_svgs', lambda ip, pw, dirs, remote: 0)
    monkeypatch.setattr('src.maintenance.backup_and_replace_templates_json', lambda ip, pw, local_path, remote_dir, base_dir: (False, 'no_local'))
    monkeypatch.setattr('src.maintenance.list_device_images', lambda name: ['img.png'])
    monkeypatch.setattr('src.maintenance.load_device_image', lambda name, fname: b'img')
    def fake_run_ssh_cmd(ip, pw, cmds):
        return ("ok", "")

    monkeypatch.setattr('src.maintenance.run_ssh_cmd', fake_run_ssh_cmd)

    ui = DummyUI()
    from src.maintenance import run_maintenance

    result = run_maintenance('dev', device, str(tmp_path), None, ui)
    assert result.get('ok') is False
    assert any('upload_suspended' in e or 'upload_suspended_failed' in e or 'upload_suspended_exception' in e for e in result.get('errors', []))
