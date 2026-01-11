"""Pytest configuration for AnimeSonarrProxy tests."""

import os
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set up environment variables for testing
os.environ.setdefault("API_KEY", "test")
os.environ.setdefault("PROWLARR_URL", "http://localhost:9696")
os.environ.setdefault("PROWLARR_API_KEY", "test")
os.environ.setdefault("DATA_DIR", str(Path(__file__).parent.parent / "data"))


@pytest.fixture
def anyio_backend():
    return "asyncio"
