#!/usr/bin/env python3
"""Remove demo objects from NetBox that were created by populate_netbox_topology."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Iterable, List

import pynetbox
import yaml

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TAG_NAME = "eda-demo-topology"
EDGE_TAG_NAME = "EDA Edge"
ISL_TAG_NAME = "ISL"
DEVICE_CUSTOM_FIELDS = [
    "operatingSystem",
    "version",
    "onBoarded",
    "nodeProfile",
]
L2VPN_CUSTOM_FIELDS = [
    "L2vpn_gateway",
    "L2vpn_ipvrf",
    "L2vpn_bridge_domain_spec",
]


def info(message: str) -> None:
    print(message, flush=True)


def load_toponode_ips() -> List[str]:
    path = BASE_DIR / "vars/topology/toponodes.yml"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    ips: List[str] = []
    for entry in data.get("toponodes", []) or []:
        ip_addr = entry.get("production_ipv4")
        if ip_addr:
            ips.append(str(ip_addr))
    return ips


def list_records(recordset: Any) -> List[Any]:
    return list(recordset)


def delete_records(records: Iterable[Any], label: str) -> int:
    count = 0
    for record in records:
        name = getattr(record, "name", getattr(record, "label", str(record)))
        info(f"Deleting {label}: {name}")
        record.delete()
        count += 1
    return count


def main() -> int:
    netbox_url = os.environ.get("NETBOX_URL", "http://127.0.0.1:8000")
    token = os.environ.get("NETBOX_TOKEN")
    if not token:
        print("NETBOX_TOKEN is required", file=sys.stderr)
        return 1

    info(f"Connecting to NetBox at {netbox_url}...")
    nb = pynetbox.api(netbox_url, token=token)

    totals: dict[str, int] = {
        "devices": 0,
        "interfaces": 0,
        "cables": 0,
        "vlans": 0,
        "vrfs": 0,
        "l2vpns": 0,
        "ip_addresses": 0,
        "tags": 0,
    }

    demo_tag = nb.extras.tags.get(name=DEFAULT_TAG_NAME)
    if demo_tag:
        devices = list_records(nb.dcim.devices.filter(tag=DEFAULT_TAG_NAME, limit=0))
        totals["devices"] = delete_records(devices, "device")

        cables = list_records(nb.dcim.cables.filter(tag=DEFAULT_TAG_NAME, limit=0))
        totals["cables"] = delete_records(cables, "cable")

        if hasattr(nb, "vpn"):
            l2vpns = list_records(nb.vpn.l2vpns.filter(tag=DEFAULT_TAG_NAME, limit=0))
            totals["l2vpns"] = delete_records(l2vpns, "L2VPN")
        else:
            l2vpns = []

        vrfs = list_records(nb.ipam.vrfs.filter(tag=DEFAULT_TAG_NAME, limit=0))
        for vrf in vrfs:
            ip_records = list_records(nb.ipam.ip_addresses.filter(vrf_id=vrf.id, limit=0))
            if ip_records:
                totals["ip_addresses"] += delete_records(ip_records, "IP address")
        totals["vrfs"] = delete_records(vrfs, "VRF")

        vlans = list_records(nb.ipam.vlans.filter(tag=DEFAULT_TAG_NAME, limit=0))
        totals["vlans"] = delete_records(vlans, "VLAN")
    else:
        l2vpns = []

    ips = load_toponode_ips()
    for ip in ips:
        cidr = f"{ip}/32"
        ip_obj = nb.ipam.ip_addresses.get(address=cidr)
        if ip_obj:
            info(f"Deleting IP address: {cidr}")
            ip_obj.delete()
            totals["ip_addresses"] += 1

    # Clean up demo-specific tags if they now have no members.
    for tag_name in (DEFAULT_TAG_NAME, EDGE_TAG_NAME, ISL_TAG_NAME):
        tag = nb.extras.tags.get(name=tag_name)
        if not tag:
            continue
        if getattr(tag, "object_count", 0) == 0:
            info(f"Deleting unused tag: {tag_name}")
            tag.delete()
            totals["tags"] += 1

    info("NetBox cleanup summary:")
    for key, value in totals.items():
        info(f"  - {key.replace('_', ' ').title()}: {value}")

    # Remove demo custom fields if present (order: L2VPN first, then devices).
    for field_name in L2VPN_CUSTOM_FIELDS + DEVICE_CUSTOM_FIELDS:
        custom_field = nb.extras.custom_fields.get(name=field_name)
        if custom_field:
            info(f"Deleting custom field: {field_name}")
            custom_field.delete()

    return 0


if __name__ == "__main__":
    sys.exit(main())
