"""Adapter registry and shared types."""

from .base import DeviceAdapter, DeviceError
from .http import HttpAdapter
from .kasa import KasaAdapter

ADAPTERS: dict[str, type] = {"kasa": KasaAdapter, "http": HttpAdapter}

__all__ = [
    "DeviceAdapter", "DeviceError", "ADAPTERS",
    "KasaAdapter", "HttpAdapter",
]
