from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class LorawanField(_Strict):
    """One uplink payload field a component contributes (LoRaWAN target).

    `cpp_expr` is the C++ expression packed into the payload; it references the
    C++ symbols the component's `globals`/`loop` declare. The `ha_*` hints are
    optional Home Assistant entity metadata, consumed by the codec's
    `getHaDeviceInfo` (the chirp2mqtt integration). They mirror the keys on
    codec.Field so a migrated field reproduces its old HA entity exactly.
    """
    name: str
    bytes: int
    cpp_type: str
    cpp_expr: str
    signed: bool = False
    scale: float = 1.0
    ha_device_class: Optional[str] = None
    ha_unit: Optional[str] = None
    ha_state_class: Optional[str] = None
    ha_diagnostic: Optional[bool] = None
    ha_icon: Optional[str] = None
    ha_divide: Optional[float] = None


class LorawanSpec(_Strict):
    lib_deps: list[str] = Field(default_factory=list)
    # Shared build prerequisites a fragment needs (e.g. "i2c", "spi"); the
    # firmware template brings the corresponding bus up once when any
    # component requires it.
    requires: list[str] = Field(default_factory=list)
    globals: str = ""
    setup: str = ""
    loop: str = ""
    fields: list[LorawanField] = Field(default_factory=list)
    downlink: Optional[str] = None


class EsphomeSpec(_Strict):
    required_components: list[str] = Field(default_factory=list)
    yaml_template: str = ""
    expander_pin_key: Optional[str] = None


class CapabilityProvides(_Strict):
    """One event/value a component emits, used as an `automations` trigger.

    `event` is the name a design references (the same name the existing ESPHome
    template `params.<event>` passthrough uses, e.g. `on_press`). `esphome`
    overrides the rendered ESPHome trigger key when it differs from `event`;
    defaults to `event` so the common case is a single line per provide.
    `channel` names the sub-block this provide lives under for multi-channel
    components (e.g. a bme280's `temperature` block); single-output components
    omit it. When set, the rendered params key is `<channel>_<event>` so the
    template's per-channel passthrough fires the right `on_value`.
    """
    event: str
    kind: Literal["event", "value"] = "event"
    esphome: Optional[str] = None
    channel: Optional[str] = None


class CapabilityAccepts(_Strict):
    """One action a component takes, used as an `automations` action target.

    `action` is the studio-side name (e.g. `turn_on`); `esphome` is the
    explicit ESPHome action verb the generator lowers to (e.g.
    `switch.turn_on`). Explicit rather than category-inferred so the mapping
    is reviewed code, not a runtime guess.
    """
    action: str
    esphome: str


class Capability(_Strict):
    """Functional layer (intent-to-device synthesis): what role this component
    plays, what events/values it `provides` to triggers, and what actions it
    `accepts` from automations. Optional per component; an unannotated
    component simply cannot be a trigger or action target."""
    role: Literal["input", "sensor", "output", "controller"]
    provides: list[CapabilityProvides] = Field(default_factory=list)
    accepts: list[CapabilityAccepts] = Field(default_factory=list)


class LibraryComponent(_Strict):
    id: str
    name: str
    category: str
    use_cases: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    electrical: Electrical = Field(default_factory=Electrical)
    esphome: EsphomeSpec = Field(default_factory=EsphomeSpec)
    lorawan: Optional[LorawanSpec] = None
    capability: Optional[Capability] = None
    params_schema: dict = Field(default_factory=dict)
    notes: Optional[str] = None
    kicad: Optional[KicadSymbolRef] = None


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


class KicadSymbolRef(_Strict):
    """Reference to a KiCad symbol library entry. Lets the schematic
    exporter (0.9) emit a SKiDL Part that points at the right symbol +
    footprint without copying KiCad's data into our library.

    `pin_map` translates our library role names (VCC, SDA, etc.) to
    the symbol's pin names where they differ -- e.g., the BME280
    module's VCC pin is named `VDD` in the KiCad symbol. Roles missing
    from the map are passed through unchanged.

    `value` overrides what's printed on the schematic (KiCad defaults
    to the symbol name); useful for parts whose useful identity differs
    from their canonical symbol (the HC-SR501 PIR uses a generic 3-pin
    header symbol but should print as "HC-SR501" on the sheet).
    """
    symbol_lib: str
    symbol: str
    footprint: Optional[str] = None
    value: Optional[str] = None
    pin_map: dict[str, str] = Field(default_factory=dict)


class RadioPins(_Strict):
    """Control/IRQ pins wiring the MCU to the LoRa transceiver. cs + rst
    are always present. SX127x (sx1276/sx1278) drive dio0; SX126x (sx1262)
    drive dio1 + busy. The unused fields stay null per chip family."""
    cs: str
    rst: str
    dio0: Optional[str] = None
    dio1: Optional[str] = None
    busy: Optional[str] = None


class Radio(_Strict):
    """LoRa/LoRaWAN transceiver metadata ESPHome's library doesn't carry.
    Only boards with this block are offered by the lorawan target. The
    firmware generator branches on `radiolib_class` to pick the RadioLib
    module and wiring constructor.

    `tcxo_voltage` is the TCXO reference for SX1262 boards (0 = none, i.e.
    a crystal); `dio2_as_rf_switch` is the SX1262 RF-switch control. Both
    are no-ops for SX127x. Getting them wrong on SX126x makes radio init
    fail and presents as 'won't join'.
    """
    chip: Literal["sx1276", "sx1278", "sx1262"]
    radiolib_class: str
    pins: RadioPins
    tcxo_voltage: float = 0.0
    dio2_as_rf_switch: bool = False

    @model_validator(mode="after")
    def _require_family_pins(self) -> "Radio":
        if self.chip == "sx1262":
            missing = [p for p in ("dio1", "busy") if getattr(self.pins, p) is None]
            if missing:
                raise ValueError(
                    f"sx1262 radio requires pins {missing} (SX126x uses dio1 + busy)"
                )
        elif self.pins.dio0 is None:
            raise ValueError(f"{self.chip} radio requires pin 'dio0' (SX127x uses dio0)")
        return self


class LibraryBoard(_Strict):
    id: str
    name: str
    mcu: str
    chip_variant: str
    framework: str
    platformio_board: str
    flash_size_mb: Optional[int] = None
    # Onboard current draw of the bare board (MCU + integrated peripherals:
    # USB-UART, regulator, status LEDs, onboard radios/displays/PMIC). Added
    # to component draw by the budget check; without it a Wi-Fi MCU's ~70-200
    # mA active draw is invisible. Convention: typical = Wi-Fi associated
    # active, peak = TX burst worst case. Datasheet-sourced per family with
    # per-board overhead for onboard parts.
    current_ma_typical: Optional[float] = None
    current_ma_peak: Optional[float] = None
    # Optional product-image URL, surfaced in the board picker.
    image: Optional[str] = None
    rails: list[Rail] = Field(default_factory=list)
    default_buses: dict = Field(default_factory=dict)
    onboard_peripherals: dict = Field(default_factory=dict)
    gpio_capabilities: dict[str, list[str]] = Field(default_factory=dict)
    enclosure: Optional[BoardEnclosure] = None
    kicad: Optional[KicadSymbolRef] = None
    radio: Optional[Radio] = None

    @property
    def has_radio(self) -> bool:
        return self.radio is not None


class ModuleComponent(_Strict):
    """One component a composite module places, with its default label
    + params. `id_hint` seeds the instance id when the module is inserted."""
    id_hint: str
    library_id: str
    label: Optional[str] = None
    params: dict = Field(default_factory=dict)


class LibraryModule(_Strict):
    """A composite module -- a physical board bundling several components.

    Selecting a module inserts every `components` entry into the design in
    one action; per-component wiring is auto-seeded the same way a
    hand-added component is. The BOM lists the module, not its parts.
    """
    id: str
    name: str
    category: str = "module"
    description: Optional[str] = None
    image: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    components: list[ModuleComponent]


class Library:
    """Lazy loader for board, component, and module definitions."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._components: dict[str, LibraryComponent] = {}
        self._boards: dict[str, LibraryBoard] = {}
        self._modules: dict[str, LibraryModule] = {}

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

    def module(self, module_id: str) -> LibraryModule:
        if module_id not in self._modules:
            path = self.root / "modules" / f"{module_id}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"Unknown module '{module_id}' (looked at {path})")
            with path.open() as f:
                data = yaml.safe_load(f)
            self._modules[module_id] = LibraryModule.model_validate(data)
        return self._modules[module_id]

    def list_modules(self) -> list[LibraryModule]:
        return [self.module(p.stem) for p in sorted((self.root / "modules").glob("*.yaml"))]


def default_library() -> Library:
    # The bundled component + board YAMLs live alongside this module
    # (wirestudio/library/components/, wirestudio/library/boards/) so
    # they ship inside the wheel.
    return Library(Path(__file__).resolve().parent)
