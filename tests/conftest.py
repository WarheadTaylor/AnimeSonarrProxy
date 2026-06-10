"""Pytest configuration for AnimeSonarrProxy tests."""

import os
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set up environment variables for testing
os.environ.setdefault("API_KEY", "test")
os.environ.setdefault("NYAA_URL", "https://nyaa.si")
os.environ.setdefault("NYAA_CATEGORY", "1_2")
os.environ.setdefault("NYAA_NO_REMAKES", "true")
os.environ.setdefault("DATA_DIR", str(Path(__file__).parent.parent / "data"))


@pytest.fixture
def anyio_backend():
    return "asyncio"
