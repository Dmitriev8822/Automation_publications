"""Shared pytest configuration for fast and integration test groups."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every non-integration test as a fast unit test.

    The default ``pytest`` command excludes tests explicitly marked as
    ``integration`` in ``pytest.ini``. Existing fast tests do not need a marker in
    each file: this hook applies the ``unit`` marker automatically unless a test
    opts into the slower integration group.
    """

    for item in items:
        if item.get_closest_marker("integration") is None:
            item.add_marker(pytest.mark.unit)
