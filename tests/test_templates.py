import os
from pathlib import Path

import pytest


def test_ensure_remote_template_dirs_calls_run_ssh(monkeypatch, tmp_path):
    called = {}

    def fake_run_ssh_cmd(ip, password, cmds):
        called['ip'] = ip
        called['cmds'] = cmds
        return ("", "")

    monkeypatch.setattr('src.templates.run_ssh_cmd', fake_run_ssh_cmd)

    from src.templates import ensure_remote_template_dirs

    ok, msg = ensure_remote_template_dirs('1.2.3.4', 'pw', '/remote/custom', '/remote/templates')
    assert ok is True
    assert 'ip' in called and called['ip'] == '1.2.3.4'


def test_upload_template_svgs_counts_uploaded(monkeypatch, tmp_path):
    # create local dirs and files
    d = tmp_path / 'templates'
    d.mkdir()
    (d / 'a.svg').write_bytes(b'<svg/>')
    (d / 'b.svg').write_bytes(b'<svg/>')
    (d / 'readme.txt').write_text('ignore')

    uploaded = []

    def fake_upload_file_ssh(ip, password, content, remote_path):
        uploaded.append(remote_path)
        return True, 'OK'

    monkeypatch.setattr('src.templates.upload_file_ssh', fake_upload_file_ssh)

    from src.templates import upload_template_svgs

    sent = upload_template_svgs('1.2.3.4', 'pw', [str(d)], '/remote/custom')
    assert sent == 2
    assert any('/remote/custom/a.svg' in p for p in uploaded)


def test_backup_and_replace_templates_json(monkeypatch, tmp_path):
    # remote has different content
    remote_content = b'{"remote":true}'

    def fake_download(ip, password, remote_path):
        return remote_content

    def fake_upload(ip, password, content, remote_path):
        # assert that content is the local content we expect
        return True, 'OK'

    monkeypatch.setattr('src.templates.download_file_ssh', fake_download)
    monkeypatch.setattr('src.templates.upload_file_ssh', fake_upload)

    local_json = tmp_path / 'templates.json'
    local_json.write_bytes(b'{"local":true}')

    from src.templates import backup_and_replace_templates_json

    ok, msg = backup_and_replace_templates_json('1.2.3.4', 'pw', str(local_json), '/remote/templates', str(tmp_path))
    assert ok is True
    # backup file must exist
    backup = tmp_path / 'templates.backup.json'
    assert backup.exists()
    assert backup.read_bytes() == remote_content
