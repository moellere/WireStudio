function decodeUplink(input) {
  var b = input.bytes;
  if (b.length < 22) {
    return { data: {}, warnings: [], errors: ['expected 22 bytes, got ' + b.length] };
  }
  var data = {};
  data.uptime_s = (((b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]) >>> 0);
  data.boot_count = (((b[4] << 8) | b[5]) >>> 0);
  data.lat = ((b[6] << 24) | (b[7] << 16) | (b[8] << 8) | b[9]) / 10000000;
  data.lon = ((b[10] << 24) | (b[11] << 16) | (b[12] << 8) | b[13]) / 10000000;
  data.alt_m = ((((b[14] << 8) | b[15]) << 16) >> 16);
  data.sats = ((b[16]) >>> 0);
  data.temp_c = ((((b[17] << 8) | b[18]) << 16) >> 16) / 100;
  data.humidity = ((b[19]) >>> 0);
  data.batt_mv = (((b[20] << 8) | b[21]) >>> 0);
  return { data: data, warnings: [], errors: [] };
}
