"""Tests for src/rmfakecloud.py — all tests use mocked requests/SSH, no real network or device."""

from unittest.mock import MagicMock, patch

import requests

from src.models import Device
from src.rmfakecloud import fetch_pairing_code, run_install

URL = "https://remarkable.example.com"
EMAIL = "anne@example.com"
PASSWORD = "secret"
DEVICE = Device(
    name="test",
    ip="192.168.1.42",
    password="sshpw",
    rmfakecloud_enabled=True,
    rmfakecloud_url=URL,
    rmfakecloud_email=EMAIL,
    rmfakecloud_password=PASSWORD,
    rmfakecloud_install_cmd="./installer-rmpro.sh install {url}",
)


def _resp(status_code=200, json_value=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_value
    return resp


# ---------------------------------------------------------------------------
# fetch_pairing_code
# ---------------------------------------------------------------------------


class TestFetchPairingCode:
    def test_happy_path(self):
        session = MagicMock()
        session.post.return_value = _resp(200)
        session.get.return_value = _resp(200, "abcdefgh")
        with patch("src.rmfakecloud.requests.Session", return_value=session):
            ok, code, error = fetch_pairing_code(URL, EMAIL, PASSWORD)
        assert (ok, code, error) == (True, "abcdefgh", "")
        session.post.assert_called_once_with(
            f"{URL}/ui/api/login",
            json={"email": EMAIL, "password": PASSWORD},
            timeout=10,
        )
        session.get.assert_called_once_with(f"{URL}/ui/api/newcode", timeout=10)

    def test_login_http_failure(self):
        session = MagicMock()
        session.post.return_value = _resp(401)
        with patch("src.rmfakecloud.requests.Session", return_value=session):
            ok, code, error = fetch_pairing_code(URL, EMAIL, PASSWORD)
        assert ok is False
        assert code == ""
        assert "401" in error
        session.get.assert_not_called()

    def test_login_network_error(self):
        session = MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")
        with patch("src.rmfakecloud.requests.Session", return_value=session):
            ok, code, error = fetch_pairing_code(URL, EMAIL, PASSWORD)
        assert ok is False
        assert "boom" in error

    def test_newcode_http_failure(self):
        session = MagicMock()
        session.post.return_value = _resp(200)
        session.get.return_value = _resp(500)
        with patch("src.rmfakecloud.requests.Session", return_value=session):
            ok, code, error = fetch_pairing_code(URL, EMAIL, PASSWORD)
        assert ok is False
        assert "500" in error

    def test_newcode_unexpected_payload(self):
        session = MagicMock()
        session.post.return_value = _resp(200)
        session.get.return_value = _resp(200, {"unexpected": "shape"})
        with patch("src.rmfakecloud.requests.Session", return_value=session):
            ok, code, error = fetch_pairing_code(URL, EMAIL, PASSWORD)
        assert ok is False
        assert code == ""
        assert error

    def test_url_trailing_slash_is_stripped(self):
        session = MagicMock()
        session.post.return_value = _resp(200)
        session.get.return_value = _resp(200, "abcdefgh")
        with patch("src.rmfakecloud.requests.Session", return_value=session):
            fetch_pairing_code(URL + "/", EMAIL, PASSWORD)
        session.post.assert_called_once_with(
            f"{URL}/ui/api/login",
            json={"email": EMAIL, "password": PASSWORD},
            timeout=10,
        )


# ---------------------------------------------------------------------------
# run_install
# ---------------------------------------------------------------------------


class TestRunInstall:
    def test_happy_path_substitutes_url_in_install_cmd(self):
        with patch("src.rmfakecloud.stream_ssh_cmd", return_value=(True, "output")) as mock_stream:
            ok, output = run_install(DEVICE)
        assert (ok, output) == (True, "output")
        mock_stream.assert_called_once_with(
            DEVICE, [f"./installer-rmpro.sh install {URL}"], on_chunk=None
        )

    def test_passes_on_chunk_through(self):
        chunks = []
        with patch(
            "src.rmfakecloud.stream_ssh_cmd",
            side_effect=lambda device, commands, on_chunk=None: (
                on_chunk("hello") if on_chunk else None,
                (True, "hello"),
            )[1],
        ):
            run_install(DEVICE, on_chunk=chunks.append)
        assert chunks == ["hello"]

    def test_failure_is_propagated(self):
        with patch("src.rmfakecloud.stream_ssh_cmd", return_value=(False, "no such file")):
            ok, output = run_install(DEVICE)
        assert ok is False
        assert output == "no such file"
