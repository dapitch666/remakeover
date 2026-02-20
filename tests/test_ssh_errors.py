import pytest
from unittest import mock


class BadClient:
    def __init__(self):
        pass

    def set_missing_host_key_policy(self, p):
        pass

    def connect(self, ip, username, password, timeout=10):
        raise Exception("connect failed")


def test_run_ssh_cmd_connect_error(monkeypatch):
    # simulate connect() raising
    monkeypatch.setattr('paramiko.SSHClient', lambda: BadClient())
    from src.ssh import run_ssh_cmd

    out, err = run_ssh_cmd('1.2.3.4', 'pw', ['echo hi'])
    assert out == ""
    assert 'connect failed' in err


class ExecErrorClient:
    def __init__(self):
        pass

    def set_missing_host_key_policy(self, p):
        pass

    def connect(self, ip, username, password, timeout=10):
        return None

    def exec_command(self, cmd):
        if 'mount | grep' in cmd:
            # return check command as readonly
            class S:
                def read(self):
                    return b'readonly'

            return None, S(), S()
        # simulate exec failure for actual command
        raise Exception('exec failure')

    def close(self):
        pass


def test_run_ssh_cmd_exec_error(monkeypatch):
    monkeypatch.setattr('paramiko.SSHClient', lambda: ExecErrorClient())
    from src.ssh import run_ssh_cmd

    out, err = run_ssh_cmd('1.2.3.4', 'pw', ['do something'])
    assert out == ""
    assert 'exec failure' in err


class BadTransport:
    def __init__(self, addr):
        pass

    def connect(self, username=None, password=None):
        raise Exception('transport connect failed')

    def close(self):
        pass


def test_upload_file_transport_connect_error(monkeypatch):
    # mock SSHClient for RW mount, but let transport.connect fail
    class MountGoodClient:
        def set_missing_host_key_policy(self, p):
            pass

        def connect(self, ip, username, password, timeout=10):
            return None

        def exec_command(self, cmd):
            class S:
                def read(self):
                    return b''

            return None, S(), S()

        def close(self):
            pass

    monkeypatch.setattr('paramiko.SSHClient', lambda: MountGoodClient())
    monkeypatch.setattr('paramiko.Transport', lambda addr: BadTransport(addr))
    from src.ssh import upload_file_ssh

    with pytest.raises(Exception) as exc:
        upload_file_ssh('1.2.3.4', 'pw', b'data', '/tmp/x')
    assert 'transport connect failed' in str(exc.value)


class BadSFTP:
    def __init__(self):
        pass

    def file(self, path, mode):
        class F:
            def __enter__(self):
                return self

            def write(self, data):
                raise Exception('sftp write failed')

            def __exit__(self, exc_type, exc, tb):
                return False

        return F()

    def close(self):
        pass


def test_upload_file_sftp_write_error(monkeypatch):
    class MountGoodClient:
        def set_missing_host_key_policy(self, p):
            pass

        def connect(self, ip, username, password, timeout=10):
            return None

        def exec_command(self, cmd):
            class S:
                def read(self):
                    return b''

            return None, S(), S()

        def close(self):
            pass

    monkeypatch.setattr('paramiko.SSHClient', lambda: MountGoodClient())
    monkeypatch.setattr('paramiko.Transport', lambda addr: mock.Mock())
    monkeypatch.setattr('paramiko.SFTPClient', mock.Mock())
    monkeypatch.setattr('paramiko.SFTPClient.from_transport', lambda t: BadSFTP())
    from src.ssh import upload_file_ssh

    ok, msg = upload_file_ssh('1.2.3.4', 'pw', b'data', '/tmp/x')
    assert ok is False
    assert 'sftp write failed' in msg


def test_download_file_sftp_error(monkeypatch):
    # simulate SFTP file read raising
    class BadSFTPRead(BadSFTP):
        def file(self, path, mode):
            class F:
                def __enter__(self):
                    return self

                def read(self):
                    raise Exception('sftp read failed')

                def __exit__(self, exc_type, exc, tb):
                    return False

            return F()

    monkeypatch.setattr('paramiko.Transport', lambda addr: mock.Mock())
    monkeypatch.setattr('paramiko.SFTPClient', mock.Mock())
    monkeypatch.setattr('paramiko.SFTPClient.from_transport', lambda t: BadSFTPRead())

    from src.ssh import download_file_ssh

    with pytest.raises(Exception) as exc:
        download_file_ssh('1.2.3.4', 'pw', '/tmp/x')
    assert 'sftp read failed' in str(exc.value)
