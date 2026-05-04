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
    # When kind == "hub_ref", names the library_id of the parent component
    # this pin must connect to (e.g., ads1115_channel.HUB has
    # parent_library_id: ads1115). The pin solver uses this to filter
    # candidates and the bus editor / inspector use it to render a
    # parent-instance dropdown.
    parent_library_id: Optional[str] = None


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


class PcbDimensions(_Strict):
    """PCB outline dimensions in millimetres. Origin at the bottom-left
    corner; PCB extends in +X (length) and +Y (width). Thickness is the
    standard 1.6mm by default; bumped to 1.0/0.8mm for thin breakouts."""
    length_mm: float
    width_mm: float
    thickness_mm: float = 1.6


class MountHole(_Strict):
    """A single PCB mounting hole. (x, y) is the hole centre measured
    from the PCB's origin corner. hole_diameter_mm is the through-hole
    diameter; the screw size matches (M2 ≈ 2.4mm, M2.5 ≈ 3.0mm,
    M3 ≈ 3.4mm clearance)."""
    x_mm: float
    y_mm: float
    hole_diameter_mm: float


class BoardPort(_Strict):
    """A connector / cutout that needs to clear the enclosure wall.
    edge values: short_a (x=0), short_b (x=length), long_a (y=0),
    long_b (y=width). offset_mm is measured from the start of the edge
    (bottom or left depending on the edge); width_mm and height_mm are
    the cutout dimensions in the enclosure-wall plane.

    height_above_pcb_mm is how far the connector body sits above the
    PCB's top surface (for centering the cutout vertically).
    """
    kind: str  # usb_micro | usb_c | usb_b | barrel_jack | sma | jst | header
    edge: str
    offset_mm: float
    width_mm: float
    height_mm: float
    height_above_pcb_mm: float = 0.0


class BoardEnclosure(_Strict):
    """Geometry needed to autogenerate a parametric enclosure shell or
    rank a community-uploaded model. Optional on each board -- modules
    that plug into a host PCB (ESP-01S etc.) skip the block."""
    pcb: PcbDimensions
    mount_holes: list[MountHole] = Field(default_factory=list)
    ports: list[BoardPort] = Field(default_factory=list)
    component_height_max_mm: float = 12.0


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
    onboard_peripherals: dict = Field(default_factory=dict)
    gpio_capabilities: dict[str, list[str]] = Field(default_factory=dict)
    enclosure: Optional[BoardEnclosure] = None


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

    def list_components(self) -> list[LibraryComponent]:
        return [self.component(p.stem) for p in sorted((self.root / "components").glob("*.yaml"))]

    def list_boards(self) -> list[LibraryBoard]:
        return [self.board(p.stem) for p in sorted((self.root / "boards").glob("*.yaml"))]


def default_library() -> Library:
    return Library(Path(__file__).resolve().parent.parent / "library")
