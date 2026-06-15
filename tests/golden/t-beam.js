function decodeUplink(input) {
  var b = input.bytes;
  var data = {};
  data.uptime_s = (((b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]) >>> 0);
  data.boot_count = (((b[4] << 8) | b[5]) >>> 0);
  data.lat = ((b[6] << 24) | (b[7] << 16) | (b[8] << 8) | b[9]) / 10000000;
  data.lon = ((b[10] << 24) | (b[11] << 16) | (b[12] << 8) | b[13]) / 10000000;
  data.alt_m = ((((b[14] << 8) | b[15]) << 16) >> 16);
  data.sats = ((b[16]) >>> 0);
  data.batt_mv = (((b[17] << 8) | b[18]) >>> 0);
  return { data: data, warnings: [], errors: [] };
}

function getHaDeviceInfo() {
  return {
    device: { manufacturer: "wirestudio", model: "wirestudio-ttgo-t-beam-us915-sub2-gps-batt" },
    entities: {
    uptime_s: {
      entity_conf: {
        value_template: "{{ value_json.object.uptime_s | int }}",
        entity_category: "diagnostic",
        device_class: "duration",
        unit_of_measurement: "s"
      }
    },
    boot_count: {
      entity_conf: {
        value_template: "{{ value_json.object.boot_count | int }}",
        entity_category: "diagnostic",
        state_class: "measurement",
        icon: "mdi:restart"
      }
    },
    lat: {
      entity_conf: {
        value_template: "{{ value_json.object.lat | float }}",
        entity_category: "diagnostic",
        unit_of_measurement: "°",
        icon: "mdi:latitude"
      }
    },
    lon: {
      entity_conf: {
        value_template: "{{ value_json.object.lon | float }}",
        entity_category: "diagnostic",
        unit_of_measurement: "°",
        icon: "mdi:longitude"
      }
    },
    alt_m: {
      entity_conf: {
        value_template: "{{ value_json.object.alt_m | float }}",
        entity_category: "diagnostic",
        state_class: "measurement",
        device_class: "distance",
        unit_of_measurement: "m"
      }
    },
    sats: {
      entity_conf: {
        value_template: "{{ value_json.object.sats | int }}",
        entity_category: "diagnostic",
        state_class: "measurement",
        icon: "mdi:satellite-variant"
      }
    },
    batt_mv: {
      entity_conf: {
        value_template: "{{ (value_json.object.batt_mv | float) / 1000 }}",
        entity_category: "diagnostic",
        state_class: "measurement",
        device_class: "voltage",
        unit_of_measurement: "V"
      }
    },
    rssi: {
      entity_conf: {
        value_template: "{{ value_json.rxInfo[-1].rssi | int }}",
        entity_category: "diagnostic",
        device_class: "signal_strength",
        unit_of_measurement: "dBm"
      }
    },
    snr: {
      entity_conf: {
        value_template: "{{ value_json.rxInfo[-1].snr | float }}",
        entity_category: "diagnostic",
        unit_of_measurement: "dB",
        icon: "mdi:wave"
      }
    },
    location: {
      integration: "device_tracker",
      entity_conf: {
        source_type: "gps",
        value_template: "{{ 'home' if (value_json.object.sats | int) > 0 else 'not_home' }}",
        json_attributes_topic: "{status_topic}",
        json_attributes_template: "{{ {'latitude': value_json.object.lat, 'longitude': value_json.object.lon, 'gps_accuracy': 10} | tojson }}"
      }
    }
    }
  };
}
