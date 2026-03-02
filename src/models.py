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
    templates: bool = True
    carousel: bool = True
    preferred_image: str | None = None

    @staticmethod
    def from_dict(name: str, data: dict[str, Any]) -> Device:
        return Device(
            name=name,
            ip=data.get("ip", ""),
            password=data.get("password", ""),
            device_type=data.get("device_type", ""),
            templates=bool(data.get("templates", True)),
            carousel=bool(data.get("carousel", True)),
            preferred_image=data.get("preferred_image"),
        )

    def to_dict(self) -> dict[str, Any]:
        d = {
            "ip": self.ip,
            "password": self.password,
            "device_type": self.device_type,
            "templates": self.templates,
            "carousel": self.carousel,
        }
        if self.preferred_image is not None:
            d["preferred_image"] = self.preferred_image
        return d

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

    def is_preferred(self, image_name: str) -> bool:
        return bool(self.preferred_image and self.preferred_image == image_name)

    def set_preferred(self, image_name: str | None) -> None:
        self.preferred_image = image_name or None
