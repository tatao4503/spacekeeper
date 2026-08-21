"""Spacekeeper: read-only local storage analysis."""

from .models import ScanOptions, ScanResult
from .scanner import scan

__all__ = ["ScanOptions", "ScanResult", "scan"]
__version__ = "0.2.0"
