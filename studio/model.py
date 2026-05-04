from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Board(_Strict):
    library_id: str
    mcu: str
    framework: str = "arduino"
    pinned_esphome_version: Optional[str] = None


class Power(_Strict):
    supply: str
    rail_voltage_v: float
    regulator: Optional[str] = None
    budget_ma: Optional[int] = None


class Requirement(_Strict):
    id: str
    kind: Literal["capability", "environment", "constraint"]
    text: str


class Component(_Strict):
    id: str
    library_id: str
    label: str
    role: Optional[str] = None
    params: dict = Field(default_factory=dict)
    locked_pins: dict[str, str] = Field(default_factory=dict)


class Bus(_Strict):
    id: str
    type: Literal["i2c", "spi", "uart", "1wire", "i2s"]
    frequency_hz: Optional[int] = None
    baud_rate: Optional[int] = None
    sda: Optional[str] = None
    scl: Optional[str] = None
    miso: Optional[str] = None
    mosi: Optional[str] = None
    clk: Optional[str] = None
    cs: Optional[str] = None
    rx: Optional[str] = None
    tx: Optional[str] = None
    lrclk: Optional[str] = None
    bclk: Optional[str] = None
    # 1-wire data pin. Single-wire bus, so the bus carries one pin field
    # rather than the multi-pin sets the synchronous buses use.
    pin: Optional[str] = None


class RailTarget(_Strict):
    kind: Literal["rail"]
    rail: str


class GpioTarget(_Strict):
    kind: Literal["gpio"]
    pin: str


class BusTarget(_Strict):
    kind: Literal["bus"]
    bus_id: str


class ExpanderPinTarget(_Strict):
    kind: Literal["expander_pin"]
    expander_id: str
    number: int
    mode: Optional[str] = None
    inverted: bool = False


ConnectionTarget = Annotated[
    Union[RailTarget, GpioTarget, BusTarget, ExpanderPinTarget],
    Field(discriminator="kind"),
]


class Connection(_Strict):
    component_id: str
    pin_role: str
    target: ConnectionTarget


class Passive(_Strict):
    id: str
    kind: Literal["resistor", "capacitor", "inductor", "diode", "transistor"]
    value: str
    between: list[str]
    purpose: Optional[str] = None


class DesignWarning(_Strict):
    level: Literal["info", "warn", "error"]
    code: str
    text: str


class Fleet(_Strict):
    device_name: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    secrets_ref: dict[str, str] = Field(default_factory=dict)


class Agent(_Strict):
    session_id: Optional[str] = None
    history_ref: Optional[str] = None


class Design(_Strict):
    schema_version: Literal["0.1"]
    id: str
    name: str
    description: Optional[str] = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    board: Board
    power: Power
    requirements: list[Requirement] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    buses: list[Bus] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    passives: list[Passive] = Field(default_factory=list)
    warnings: list[DesignWarning] = Field(default_factory=list)
    esphome_extras: dict = Field(default_factory=dict)
    fleet: Optional[Fleet] = None
    agent: Optional[Agent] = None
