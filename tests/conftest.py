"""Shared pytest configuration.

Loads the offline guard (``scripts/offline_guard.py``) so that a plain ``uv run pytest``
blocks network access. CI also forces it with ``-p offline_guard``, so removing this line
does not switch the guard off there.
"""

pytest_plugins = ("offline_guard",)
