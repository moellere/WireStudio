from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from wirestudio.library import Library
from wirestudio.model import Design, DesignWarning

if TYPE_CHECKING:
    from fastapi import APIRouter

    from wirestudio.targets.build_backend import BuildBackend


class TargetPlugin(ABC):
    """A generation target: the kind of artifact a design compiles to.

    The default ``esphome`` target renders ESPHome YAML; ``lorawan`` produces
    flashable LoRaWAN firmware. The interface stays deliberately small -- only
    the behavior with a live consumer today. Target-specific HTTP endpoints
    (flash, provision, monitor) and a firmware/yaml ``generate()`` method get
    added to this interface in the phase that first needs them, not before.
    """

    id: str

    @abstractmethod
    def board_ids(self, library: Library) -> list[str]:
        """Library board ids selectable for this target, sorted."""

    @abstractmethod
    def component_ids(self, library: Library) -> list[str]:
        """Library component ids selectable for this target, sorted."""

    @abstractmethod
    def generate(self, design: Design, library: Library) -> dict[str, str]:
        """Generate artifacts. Returns a map of filename to contents."""

    def validate(self, design: Design, library: Library) -> list[DesignWarning]:
        """Target-specific, permissive design checks.

        Returns warnings to append to ``design.warnings``; never raises.
        Default: no extra checks (the esphome target relies on the shared
        compatibility checker).
        """
        return []

    def router(self, library: Library) -> "Optional[APIRouter]":
        """Target-specific HTTP endpoints, mounted by the API under ``/<id>``.

        Default None: esphome's endpoints are the existing top-level routes.
        lorawan returns a router for compile/flash/provision.
        """
        return None

    def build_backend(self) -> "Optional[BuildBackend]":
        """The build path that turns this target's generated firmware into a
        flashable artifact (probe / enqueue / stream / fetch).

        Default None: not every target builds in-studio (esphome hands off to
        fleet-for-esphome via the /fleet/* routes). lorawan returns the in-pod
        PlatformIO backend; a remote LoRaWAN build worker would slot in here as
        a second implementation without touching the endpoints.
        """
        return None


_REGISTRY: dict[str, TargetPlugin] = {}


def register(plugin: TargetPlugin) -> None:
    if plugin.id in _REGISTRY:
        raise ValueError(f"target {plugin.id!r} is already registered")
    _REGISTRY[plugin.id] = plugin


def get_target(target_id: str) -> TargetPlugin:
    try:
        return _REGISTRY[target_id]
    except KeyError:
        raise KeyError(f"unknown target {target_id!r}") from None


def target_ids() -> list[str]:
    return sorted(_REGISTRY)
