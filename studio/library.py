from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PullUp(_Strict):
    required: bool = True
    value: str
    to: str = "VCC"


class Pin(_Strict):
    role: str
    kind: str
    voltage: Optional[float] = None
    pull_up: Optional[PullUp] = None


class PassiveSpec(_Strict):
    kind: str
    value: str
    between: list[str]
    purpose: Optional[str] = None


class Electrical(_Strict):
    vcc_min: Optional[float] = None
    vcc_max: Optional[float] = None
    current_ma_typical: Optional[float] = None
    current_ma_peak: Optional[float] = None
    pins: list[Pin] = Field(default_factory=list)
    passives: list[PassiveSpec] = Field(default_factory=list)


class EsphomeSpec(_Strict):
    required_components: list[str] = Field(default_factory=list)
    yaml_template: str = ""


class LibraryComponent(_Strict):
    id: str
    name: str
    category: str
    use_cases: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    electrical: Electrical = Field(default_factory=Electrical)
    esphome: EsphomeSpec = Field(default_factory=EsphomeSpec)
    params_schema: dict = Field(default_factory=dict)
    notes: Optional[str] = None


class Rail(_Strict):
    name: str
    voltage: float
    source: Optional[str] = None


class LibraryBoard(_Strict):
    id: str
    name: str
    mcu: str
    chip_variant: str
    framework: str
    platformio_board: str
    flash_size_mb: Optional[int] = None
    rails: list[Rail] = Field(default_factory=list)
    default_buses: dict = Field(default_factory=dict)
    gpio_capabilities: dict[str, list[str]] = Field(default_factory=dict)


class Library:
    """Lazy loader for board and component definitions."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._components: dict[str, LibraryComponent] = {}
        self._boards: dict[str, LibraryBoard] = {}

    def component(self, library_id: str) -> LibraryComponent:
        if library_id not in self._components:
            path = self.root / "components" / f"{library_id}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"Unknown component '{library_id}' (looked at {path})")
            with path.open() as f:
                data = yaml.safe_load(f)
            self._components[library_id] = LibraryComponent.model_validate(data)
        return self._components[library_id]

    def board(self, library_id: str) -> LibraryBoard:
        if library_id not in self._boards:
            path = self.root / "boards" / f"{library_id}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"Unknown board '{library_id}' (looked at {path})")
            with path.open() as f:
                data = yaml.safe_load(f)
            self._boards[library_id] = LibraryBoard.model_validate(data)
        return self._boards[library_id]


def default_library() -> Library:
    return Library(Path(__file__).resolve().parent.parent / "library")
