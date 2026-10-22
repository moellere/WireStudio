# design.json reference

Generated from [`design.schema.json`](../wirestudio/schema/design.schema.json)
by `scripts/schema_doc.py`; do not edit by hand. A field path ending in
`[]` is an array element; `{}` is a map value. A connection `target`
is one of several shapes, listed under its `kind`.

Current `schema_version`: **0.3**. Older documents are accepted
and migrated on load (`wirestudio.migrate`); see
[`roadmap.md`](roadmap.md) section 1 for the freeze.

| Field | Type | Required | Values | Description |
|---|---|---|---|---|
| `schema_version` | enum | yes | `"0.1"`, `"0.2"`, `"0.3"` | 0.3 is current; older versions are accepted and migrated on load (0.1: the lorawan.gps / dht22 / oled blocks become components; 0.2: fields nothing read are dropped). |
| `id` | string | yes |  |  |
| `name` | string | yes |  |  |
| `description` | string |  |  | Shown in the design pane and in the saved-design and example lists. |
| `board` | object | yes |  |  |
| `board.library_id` | string | yes |  |  |
| `board.mcu` | string | yes |  |  |
| `board.framework` | string |  | default `"arduino"` |  |
| `board.flash_size_mb` | enum |  | `4`, `8`, `16`, `32` |  |
| `power` | object | yes |  | The supply the design was made for. `budget_ma` is the only field the pin solver and generators read (the current-budget warning and the ASCII summary); `supply`, `rail_voltage_v` and `regulator` are the design's record and appear in no artifact. |
| `power.supply` | string | yes |  |  |
| `power.rail_voltage_v` | number | yes |  |  |
| `power.regulator` | string |  |  |  |
| `power.budget_ma` | integer |  |  |  |
| `requirements` | array |  |  | The intent the design was built to meet, edited in the inspector and by the agent. No generator reads it. |
| `requirements[]` | object |  |  |  |
| `requirements[].id` | string | yes |  |  |
| `requirements[].kind` | enum | yes | `"capability"`, `"environment"`, `"constraint"` |  |
| `requirements[].text` | string | yes |  |  |
| `components` | array |  |  |  |
| `components[]` | object |  |  |  |
| `components[].id` | string | yes |  |  |
| `components[].library_id` | string | yes |  |  |
| `components[].label` | string | yes |  |  |
| `components[].role` | string |  |  | Free text shown in the inspector; no generator reads it. |
| `components[].params` | object |  |  | Values for the library component's params_schema, read by its ESPHome template and footprint. |
| `components[].locked_pins` | object |  |  | Pin role -> board pin the solver must keep. |
| `components[].locked_pins{}` | string |  |  |  |
| `components[].module` | object |  |  | Set when the component was inserted as part of a composite module; the BOM lists the module once per instance instead of this part. |
| `components[].module.module_id` | string | yes |  |  |
| `components[].module.instance` | string | yes |  |  |
| `buses` | array |  |  |  |
| `buses[]` | object |  |  |  |
| `buses[].id` | string | yes |  |  |
| `buses[].type` | enum | yes | `"i2c"`, `"spi"`, `"uart"`, `"1wire"`, `"i2s"` |  |
| `buses[].frequency_hz` | integer |  |  |  |
| `buses[].baud_rate` | integer |  |  |  |
| `buses[].sda` | string |  |  |  |
| `buses[].scl` | string |  |  |  |
| `buses[].miso` | string |  |  |  |
| `buses[].mosi` | string |  |  |  |
| `buses[].clk` | string |  |  |  |
| `buses[].cs` | string |  |  |  |
| `buses[].rx` | string |  |  |  |
| `buses[].tx` | string |  |  |  |
| `buses[].lrclk` | string |  |  |  |
| `buses[].bclk` | string |  |  |  |
| `buses[].pin` | string |  |  | 1-wire data pin. |
| `buses[].parity` | enum |  | `"NONE"`, `"EVEN"`, `"ODD"` | UART parity; omitted means NONE. |
| `connections` | array |  |  |  |
| `connections[]` | object |  |  |  |
| `connections[].component_id` | string | yes |  |  |
| `connections[].pin_role` | string | yes |  |  |
| `connections[].target` | one of | yes |  |  |
| `connections[].target<kind=rail>.kind` | const | yes | `"rail"` |  |
| `connections[].target<kind=rail>.rail` | string | yes |  |  |
| `connections[].target<kind=gpio>.kind` | const | yes | `"gpio"` |  |
| `connections[].target<kind=gpio>.pin` | string | yes |  |  |
| `connections[].target<kind=bus>.kind` | const | yes | `"bus"` |  |
| `connections[].target<kind=bus>.bus_id` | string | yes |  |  |
| `connections[].target<kind=expander_pin>.kind` | const | yes | `"expander_pin"` |  |
| `connections[].target<kind=expander_pin>.expander_id` | string | yes |  |  |
| `connections[].target<kind=expander_pin>.number` | integer | yes |  |  |
| `connections[].target<kind=expander_pin>.mode` | enum |  | `"INPUT"`, `"INPUT_PULLUP"`, `"INPUT_PULLDOWN"`, `"OUTPUT"`, `"OUTPUT_OPEN_DRAIN"` |  |
| `connections[].target<kind=expander_pin>.inverted` | boolean |  |  |  |
| `connections[].target<kind=component>.kind` | const | yes | `"component"` |  |
| `connections[].target<kind=component>.component_id` | string | yes |  |  |
| `connections[].target<kind=net>.kind` | const | yes | `"net"` |  |
| `connections[].target<kind=net>.component_id` | string |  |  |  |
| `connections[].target<kind=net>.net` | string |  |  |  |
| `part_overrides` | object |  |  | Drawer substitutions for subcircuit parts: '<component id>.<part id>' -> MPN. Changes the printed value only; symbol and footprint stay. |
| `part_overrides{}` | string |  |  |  |
| `passives` | array |  |  |  |
| `passives[]` | object |  |  |  |
| `passives[].id` | string | yes |  |  |
| `passives[].kind` | enum | yes | `"resistor"`, `"capacitor"`, `"inductor"`, `"diode"`, `"transistor"` |  |
| `passives[].value` | string | yes |  |  |
| `passives[].between` | array | yes |  |  |
| `passives[].between[]` | string |  |  |  |
| `passives[].purpose` | string |  |  |  |
| `automations` | array |  |  |  |
| `automations[]` | object |  |  |  |
| `automations[].id` | string | yes |  |  |
| `automations[].trigger` | object | yes |  |  |
| `automations[].trigger.component_id` | string | yes |  |  |
| `automations[].trigger.event` | string | yes |  |  |
| `automations[].trigger.channel` | string |  |  | Sub-block on multi-channel components (e.g. "temperature" on a bme280); omit for single-output. |
| `automations[].trigger.above` | number |  |  | Lower bound for an on_value_range trigger; value must rise above this to fire. Set only when event is on_value_range. |
| `automations[].trigger.below` | number |  |  | Upper bound for an on_value_range trigger; value must fall below this to fire. Set only when event is on_value_range. |
| `automations[].conditions` | array |  |  | Predicates that gate the actions; the trigger must fire AND every condition must hold. Lowered to ESPHome's `if: { condition: ..., then: [...] }`. |
| `automations[].conditions[]` | object |  |  |  |
| `automations[].conditions[].component_id` | string | yes |  |  |
| `automations[].conditions[].predicate` | string | yes |  |  |
| `automations[].actions` | array | yes |  |  |
| `automations[].actions[]` | object |  |  |  |
| `automations[].actions[].component_id` | string | yes |  |  |
| `automations[].actions[].action` | string | yes |  |  |
| `automations[].actions[].args` | object |  |  |  |
| `automations[].actions[].transform` | object |  |  | Action arg name -> C++ expression in terms of x (the trigger's value); lowered to !lambda "return <expr>;". |
| `automations[].actions[].transform{}` | string |  |  |  |
| `warnings` | array |  |  | What the last validate pass found. Permissive mode records violations here and generation proceeds; strict mode blocks on warn and error entries. |
| `warnings[]` | object |  |  |  |
| `warnings[].level` | enum | yes | `"info"`, `"warn"`, `"error"` |  |
| `warnings[].code` | string | yes |  |  |
| `warnings[].text` | string | yes |  |  |
| `esphome_extras` | object |  |  | Raw ESPHome sections merged into the rendered config after the generated ones: header-level overrides and anything the library does not model. |
| `fleet` | object |  |  |  |
| `fleet.device_name` | string |  |  |  |
| `fleet.tags` | array |  |  | Labels shown in the inspector; not passed to fleet-for-esphome or ChirpStack. |
| `fleet.tags[]` | string |  |  |  |
| `fleet.secrets_ref` | object |  |  |  |
| `fleet.secrets_ref{}` | string |  |  |  |
| `target` | enum |  | `"esphome"`, `"lorawan"` | What generate produces: ESPHome YAML or standalone LoRaWAN firmware. The Tasmota template is an export of an esphome design (POST /tasmota/template), not a target value. |
| `strict` | boolean |  | default `false` | When true, warn/error compatibility entries and design warnings block generation instead of surfacing permissively. |
| `lorawan` | object |  |  |  |
| `lorawan.region` | enum |  | `"US915"`, `"EU868"`, `"AU915"`, `"AS923"` |  |
| `lorawan.sub_band` | integer |  | default `2` |  |
| `lorawan.join_eui` | string |  |  | MSB hex; both paths default to the zero EUI. The DevEUI and AppKey are not design fields: the device or the provision request supplies the one, ChirpStack mints the other. |
| `lorawan.payload` | array |  |  | Ordered uplink field list for the ESPHome external-component target path (`lorawan-for-esphome`). Each entry packs a sensor's current value into the uplink; the ChirpStack decoder is generated from the same list so device and server stay in lockstep. Unused by the standalone Arduino path. |
| `lorawan.payload[]` | object |  |  |  |
| `lorawan.payload[].sensor` | string | yes |  | design-level component_id whose value goes into this slot |
| `lorawan.gps` | object |  |  | Deprecated: sugar for a `uart_gps` component on a UART bus. Lowered to that component before generation; removed at 1.0. |
| `lorawan.gps.rx_pin` | string | yes |  |  |
| `lorawan.gps.tx_pin` | string | yes |  |  |
| `lorawan.gps.baud` | integer |  | default `9600` |  |
| `lorawan.dht22` | object |  |  | Deprecated: sugar for a `dht` component with DATA on `pin`. Lowered before generation; removed at 1.0. |
| `lorawan.dht22.pin` | string | yes |  |  |
| `lorawan.oled` | object |  |  | Deprecated: sugar for an `ssd1306` component on the board's I2C bus. Lowered before generation; removed at 1.0. |
| `lorawan.oled.enabled` | boolean |  | default `true` |  |
