"""Workbench phase 4: is each LoRaWAN board still radiating like it used to?

`uplinks` proves a board was heard recently. This compares how well it was
heard: ChirpStack keeps, per device, the RSSI and SNR its gateways measured on
every uplink, across every channel the device hops over. The last 24 hours
are set against the device's own 7 days before that, so a board whose antenna
came loose, or whose radio is failing, shows up as a drop even while it still
gets through.

The bench SDR cannot do this job: its power measurement averages one window,
which washes out a ~100 ms LoRa burst, and its burst-level mode at the Pi's
safe sample rate hears one or two of sub-band 2's eight channels.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

MIN_SNR_DB = -7.5      # SF7's demodulation floor; below it uplinks start to drop
MAX_DROP_DB = 10.0


@dataclass
class Link:
    packets: int
    rssi: Optional[float]
    snr: Optional[float]


def _weighted(metrics) -> Link:
    counts = list(metrics.rx_packets.datasets[0].data) if metrics.rx_packets.datasets else []
    rssi = list(metrics.gw_rssi.datasets[0].data) if metrics.gw_rssi.datasets else []
    snr = list(metrics.gw_snr.datasets[0].data) if metrics.gw_snr.datasets else []
    total = 0.0
    r_sum = s_sum = 0.0
    for i, n in enumerate(counts):
        if n <= 0 or i >= len(rssi) or i >= len(snr):
            continue
        total += n
        r_sum += rssi[i] * n
        s_sum += snr[i] * n
    if not total:
        return Link(0, None, None)
    return Link(int(total), r_sum / total, s_sum / total)


def links(stubs, auth, dev_eui: str, *, now: Optional[float] = None) -> tuple[Link, Link]:
    """(last 24 hours, the 7 days before them) for `dev_eui`."""
    from chirpstack_api import api, common
    from google.protobuf.timestamp_pb2 import Timestamp

    now = now if now is not None else time.time()

    def ts(t: float) -> Timestamp:
        out = Timestamp()
        out.FromSeconds(int(t))
        return out

    day = 86400
    recent = stubs.device.GetLinkMetrics(api.GetDeviceLinkMetricsRequest(
        dev_eui=dev_eui, start=ts(now - day), end=ts(now), aggregation=common.Aggregation.HOUR),
        metadata=auth)
    before = stubs.device.GetLinkMetrics(api.GetDeviceLinkMetricsRequest(
        dev_eui=dev_eui, start=ts(now - 8 * day), end=ts(now - day), aggregation=common.Aggregation.DAY),
        metadata=auth)
    return _weighted(recent), _weighted(before)


def judge(recent: Link, baseline: Link, *, min_snr: float = MIN_SNR_DB,
          max_drop: float = MAX_DROP_DB) -> tuple[bool, str]:
    if not recent.packets:
        return False, "no uplinks in the last 24 h to measure"
    detail = f"rssi {recent.rssi:.1f} dBm, snr {recent.snr:.1f} dB over {recent.packets} uplinks in 24 h"
    if baseline.packets:
        detail += f" (7-day: rssi {baseline.rssi:.1f} dBm, snr {baseline.snr:.1f} dB)"
    else:
        detail += " (no 7-day baseline yet)"
    if recent.snr < min_snr:
        return False, f"{detail} -- snr below {min_snr} dB, uplinks will start to drop"
    if baseline.packets and baseline.rssi - recent.rssi > max_drop:
        return False, (f"{detail} -- rssi {baseline.rssi - recent.rssi:.1f} dB below its own baseline; "
                       f"check the antenna and its connector")
    return True, detail
