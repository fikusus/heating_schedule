"""Serving and auto-registration of the Heating Schedule Lovelace card.

The card lives inside the integration, so it has to be served and wired into
the frontend by us. Two things make that fragile, and both are handled here:

* Browsers (and HA's service worker) cache aggressively. The card URL therefore
  carries a hash of the file content, and the file is served with headers that
  force revalidation, so a changed card is always picked up.
* Lovelace may not be set up yet when our config entry loads, in which case the
  permanent resource registration would be skipped. We wait for it instead.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from aiohttp import web

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_when_setup

from .const import CARD_FILENAME, CARD_URL_PATH, CARD_VERSION, DOMAIN

_LOGGER = logging.getLogger(__name__)

LOVELACE_DOMAIN = "lovelace"

DATA_CARD_URL = "_card_url"
DATA_FRONTEND_REGISTERED = "_frontend_registered"


class HeatingScheduleCardView(HomeAssistantView):
    """Serve the card JS, always revalidated."""

    url = CARD_URL_PATH
    name = f"{DOMAIN}:card"
    requires_auth = False

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    async def get(self, request: web.Request) -> web.StreamResponse:
        """Return the card source."""
        if not self._file_path.is_file():
            _LOGGER.error("Card file is missing: %s", self._file_path)
            return web.Response(status=404, text="card not found")

        return web.FileResponse(
            self._file_path,
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                # A stale card breaks the dashboard, a conditional request costs
                # nothing. Let the browser keep the file, but make it ask first.
                "Cache-Control": "no-cache, must-revalidate",
            },
        )


def _fingerprint(file_path: Path) -> str:
    """Version string derived from the card content, used as the ?v= buster."""
    try:
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()[:10]
    except OSError as err:
        _LOGGER.warning("Could not fingerprint %s: %s", file_path, err)
        return CARD_VERSION
    return f"{CARD_VERSION}.{digest}"


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card and make the frontend load it."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_FRONTEND_REGISTERED):
        return

    file_path = Path(
        hass.config.path(f"custom_components/{DOMAIN}/www/{CARD_FILENAME}")
    )
    version = await hass.async_add_executor_job(_fingerprint, file_path)
    card_url = f"{CARD_URL_PATH}?v={version}"

    try:
        hass.http.register_view(HeatingScheduleCardView(file_path))
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Could not serve the card at %s: %s", CARD_URL_PATH, err)
        return

    domain_data[DATA_FRONTEND_REGISTERED] = True
    domain_data[DATA_CARD_URL] = card_url

    # Injected into index.html. Covers YAML-mode Lovelace and gets the module
    # loading early, but it rides along with the cached app shell, so it is a
    # complement to the resource registration below, never a replacement.
    try:
        add_extra_js_url(hass, card_url)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not add %s to the frontend: %s", card_url, err)

    async_when_setup(hass, LOVELACE_DOMAIN, _async_lovelace_ready)

    _LOGGER.info(
        "Heating Schedule card served at %s (file: %s)", card_url, file_path
    )


async def _async_lovelace_ready(hass: HomeAssistant, component: str) -> None:
    """Register the card as a permanent Lovelace resource once Lovelace is up."""
    card_url = hass.data.get(DOMAIN, {}).get(DATA_CARD_URL)
    if card_url is None:
        return
    await _async_register_lovelace_resource(hass, card_url)


async def _async_register_lovelace_resource(
    hass: HomeAssistant, card_url: str
) -> bool:
    """Create or update our entry in the Lovelace resource collection.

    Returns False when Lovelace is in YAML mode or the collection is not
    reachable; in that case the user has to list the resource themselves.
    """
    try:
        from homeassistant.components.lovelace import ResourceYAMLCollection
    except ImportError:
        return False

    lovelace = hass.data.get(LOVELACE_DOMAIN)
    if lovelace is None:
        return False

    resources = getattr(lovelace, "resources", None)
    if resources is None:
        resources = lovelace.get("resources") if isinstance(lovelace, dict) else None
    if resources is None:
        return False

    if isinstance(resources, ResourceYAMLCollection):
        _LOGGER.info(
            "Lovelace runs in YAML mode; add %s to your resources manually",
            card_url,
        )
        return False

    if hasattr(resources, "async_load") and not getattr(resources, "loaded", True):
        try:
            await resources.async_load()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("resources.async_load failed: %s", err)

    try:
        items = list(resources.async_items())
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("resources.async_items failed: %s", err)
        return False

    matching = [
        item
        for item in items
        if str(item.get("url", "")).split("?", 1)[0] == CARD_URL_PATH
    ]

    if matching:
        for item in matching:
            if item.get("url") == card_url:
                continue
            try:
                await resources.async_update_item(
                    item["id"], {"url": card_url, "res_type": "module"}
                )
                _LOGGER.info("Updated Lovelace resource to %s", card_url)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("resources.async_update_item failed: %s", err)
        return True

    try:
        await resources.async_create_item({"url": card_url, "res_type": "module"})
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not add Lovelace resource %s: %s", card_url, err)
        return False

    _LOGGER.info("Registered Lovelace resource %s", card_url)
    return True
