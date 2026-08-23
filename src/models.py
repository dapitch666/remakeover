from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.constants import DEFAULT_DEVICE_TYPE, DEVICE_SIZES


@dataclass
class Device:
    """Represents a reMarkable device configuration.

    Use `Device.from_dict(name, data)` to construct from the config structure.
    """

    name: str
    ip: str
    password: str
    device_type: str = ""
    firmware_version: str = ""
    sleep_screen_enabled: bool = False
    rmfakecloud_enabled: bool = False
    rmfakecloud_url: str = ""
    rmfakecloud_email: str = ""
    rmfakecloud_password: str = ""
    rmfakecloud_install_cmd: str = ""

    @staticmethod
    def from_dict(name: str, data: dict[str, Any]) -> Device:
        return Device(
            name=name,
            ip=data.get("ip", ""),
            password=data.get("password") or "",
            device_type=data.get("device_type", ""),
            firmware_version=str(data.get("firmware_version", "")),
            sleep_screen_enabled=data.get("sleep_screen_enabled", False),
            rmfakecloud_enabled=data.get("rmfakecloud_enabled", False),
            rmfakecloud_url=data.get("rmfakecloud_url", ""),
            rmfakecloud_email=data.get("rmfakecloud_email", ""),
            rmfakecloud_password=data.get("rmfakecloud_password", ""),
            rmfakecloud_install_cmd=data.get("rmfakecloud_install_cmd", ""),
        )

    def resolve_type(
        self,
        device_sizes: dict[str, Any] = DEVICE_SIZES,
        default: str = DEFAULT_DEVICE_TYPE,
    ) -> str:
        """Return the device type string if known, otherwise *default*.

        Both arguments are optional: when called without arguments the
        canonical ``DEVICE_SIZES`` catalogue and ``DEFAULT_DEVICE_TYPE``
        are used automatically.
        """
        if self.device_type in device_sizes:
            return self.device_type
        return default
