"""Discovers country plugins registered as entry points."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from fuelprice.core.plugin import CountryPlugin

ENTRY_POINT_GROUP = "fuelprice.countries"
log = logging.getLogger(__name__)


def discover_plugins() -> dict[str, CountryPlugin]:
    plugins: dict[str, CountryPlugin] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
            plugin = cls()
        except Exception:
            log.exception("Failed to load country plugin %r", ep.name)
            continue
        if not isinstance(plugin, CountryPlugin):
            log.error("Entry point %r is not a CountryPlugin", ep.name)
            continue
        if plugin.code in plugins:
            log.error("Duplicate country code %r from entry point %r", plugin.code, ep.name)
            continue
        plugins[plugin.code] = plugin
    return plugins
