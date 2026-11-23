"""AI Briefing: evidence-first briefings on developments in AI and software engineering.

One package, run as short scheduled jobs (ADR-001). The modules and what each owns are in
RFC v0.3 §3.3.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ai-briefing")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
