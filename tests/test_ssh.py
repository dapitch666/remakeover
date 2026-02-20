import io
from unittest import mock


class FakeStd:
    def __init__(self, data=b""):
        self._data = data

    def read(self):
        return self._data


class FakeClient:
    def __init__(self):
        self.exec_calls = []

    def set_missing_host_key_policy(self, p):
        pass

    def connect(self, ip, username, password, timeout=10):
        pass

    def exec_command(self, cmd):
        self.exec_calls.append(cmd)
        if 'if mount' in cmd:
            return None, FakeStd(b'writable'), FakeStd(b'')
        if cmd.strip().startswith('echo ok'):
            return None, FakeStd(b'ok'), FakeStd(b'')
        return None, FakeStd(b'CMDOUT'), FakeStd(b'')

    def close(self):
        pass


class FakeSFTPFile:
    def __init__(self, initial=b'remote-bytes'):
        self._buf = io.BytesIO()
        self._buf.write(initial)
        self._buf.seek(0)

    def write(self, data):
        # emulate writing: just accept bytes
        return self._buf.write(data)

    def read(self):
        self._buf.seek(0)
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSFTP:
    def __init__(self):
        pass

    def file(self, path, mode):
        if 'r' in mode:
            return FakeSFTPFile()
        return FakeSFTPFile(initial=b'')

    def close(self):
        pass


class FakeTransport:
    def __init__(self, addr):
        pass

    def connect(self, username=None, password=None):
        pass
    def close(self):
        pass


def test_run_ssh_cmd(monkeypatch):
    monkeypatch.setattr('paramiko.SSHClient', lambda: FakeClient())
    from src.ssh import run_ssh_cmd

    out, err = run_ssh_cmd('1.2.3.4', 'pw', ['echo hi'])
    assert 'CMDOUT' in out


def test_run_ssh_cmd_no_remount(monkeypatch):
    monkeypatch.setattr('paramiko.SSHClient', lambda: FakeClient())
    from src.ssh import run_ssh_cmd_no_remount

    out, err = run_ssh_cmd_no_remount('1.2.3.4', 'pw', ['echo hi'])
    assert 'CMDOUT' in out


def test_test_ssh_connection(monkeypatch):
    monkeypatch.setattr('paramiko.SSHClient', lambda: FakeClient())
    from src.ssh import test_ssh_connection

    ok, err = test_ssh_connection('1.2.3.4', 'pw')
    assert ok is True


def test_upload_and_download_file_ssh(monkeypatch):
    # Patch Transport and SFTPClient.from_transport
    monkeypatch.setattr('paramiko.Transport', lambda addr: FakeTransport(addr))
    monkeypatch.setattr('paramiko.SFTPClient', mock.Mock())
    monkeypatch.setattr('paramiko.SFTPClient.from_transport', lambda transport: FakeSFTP())
    # Also mock SSHClient used for the initial RW mount attempt
    monkeypatch.setattr('paramiko.SSHClient', lambda: FakeClient())

    from src.ssh import upload_file_ssh, download_file_ssh

    ok, msg = upload_file_ssh('1.2.3.4', 'pw', b'hello', '/tmp/remote')
    assert ok is True

    content = download_file_ssh('1.2.3.4', 'pw', '/tmp/remote')
    assert b'remote-bytes' in content
