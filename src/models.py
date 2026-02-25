from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


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
    preferred_image: Optional[str] = None

    @staticmethod
    def from_dict(name: str, data: Dict[str, Any]) -> "Device":
        return Device(
            name=name,
            ip=data.get("ip", ""),
            password=data.get("password", ""),
            device_type=data.get("device_type", ""),
            templates=bool(data.get("templates", True)),
            carousel=bool(data.get("carousel", True)),
            preferred_image=data.get("preferred_image"),
        )

    def to_dict(self) -> Dict[str, Any]:
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

    def resolve_type(self, device_sizes: Dict[str, Any], default: str) -> str:
        """Return the device type string if known, otherwise the provided default."""
        if self.device_type in device_sizes:
            return self.device_type
        return default

    def is_preferred(self, image_name: str) -> bool:
        return bool(self.preferred_image and self.preferred_image == image_name)

    def set_preferred(self, image_name: Optional[str]):
        if image_name:
            self.preferred_image = image_name
        else:
            self.preferred_image = None
