"""Shared fixtures for pages/ AppTest-based integration tests."""

import pytest


@pytest.fixture(autouse=True)
def pages_test_context():
    """Provide a consistent autouse fixture hook for page tests."""
    yield
