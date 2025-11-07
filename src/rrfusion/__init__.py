"""Core utilities shared by the rrfusion MCP + DB stub stack."""

from importlib import metadata


def get_version() -> str:
    try:
        return metadata.version("rrfusion")
    except metadata.PackageNotFoundError:
        return "0.0.0"


__all__ = ["get_version"]
