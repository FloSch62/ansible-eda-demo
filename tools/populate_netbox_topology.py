#!/usr/bin/env python3
"""Populate NetBox with demo topology data using local YAML definitions."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pynetbox
import requests
import yaml

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SITE_NAME = "EDA Demo"
DEFAULT_TAG_NAME = "eda-demo-topology"
EDGE_TAG_NAME = "EDA Edge"
ISL_TAG_NAME = "ISL"

EDGE_INTERFACE_TYPE = "10gbase-x-sfpp"
FABRIC_INTERFACE_TYPE = "100gbase-x-qsfp28"
MGMT_INTERFACE_TYPE = "virtual"

SPEED_TO_INTERFACE_TYPE = {
    "10G": EDGE_INTERFACE_TYPE,
    "25G": "25gbase-x-sfp28",
    "40G": "40gbase-qsfpp",
    "100G": FABRIC_INTERFACE_TYPE,
}

DEVICE_CUSTOM_FIELDS = {
    "operatingSystem": {
        "type": "text",
        "label": "Operating System",
        "description": "Operating system reported to Nokia EDA",
    },
    "version": {
        "type": "text",
        "label": "Software Version",
        "description": "Software version reported to Nokia EDA",
    },
    "onBoarded": {
        "type": "boolean",
        "label": "On-boarded",
        "description": "Whether the node has been onboarded into Nokia EDA",
        "default": False,
    },
    "nodeProfile": {
        "type": "text",
        "label": "Node Profile",
        "description": "Nokia EDA NodeProfile name referenced by the device",
    },
}

L2VPN_CUSTOM_FIELDS = {
    "L2vpn_gateway": {
        "type": "object",
        "label": "Gateway",
        "description": "Gateway IP address for L2VPN.",
        "object_type": "ipam.ipaddress",
    },
    "L2vpn_ipvrf": {
        "type": "object",
        "label": "IP-VRF",
        "description": "Associated IP VRF for L2VPN.",
        "object_type": "ipam.vrf",
    },
    "L2vpn_bridge_domain_spec": {
        "type": "json",
        "label": "Bridge Domain Spec",
        "description": "Bridge domain specification for Nokia EDA.",
    },
}


@dataclass
class EdgeInterfaceSpec:
    name: str
    labels: Dict[str, Any]
    members: List[Dict[str, Any]]
    speed: Optional[str]


@dataclass
class BridgeDomainSpec:
    name: str
    source_spec: Dict[str, Any]
    gateway: Optional[str]


@dataclass
class VirtualNetworkSpec:
    name: str
    namespace: str
    routers: List[Dict[str, Any]]
    bridge_domains: List[BridgeDomainSpec]
    vlans: List[Dict[str, Any]]


class TopologyLoader:
    """Load demo topology YAML definitions."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def load_yaml(self, relative_path: str) -> Dict[str, Any]:
        path = self.root / relative_path
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Expected mapping at {path}, got {type(data).__name__}")
        return data

    def toponodes(self) -> List[Dict[str, Any]]:
        return self.load_yaml("vars/topology/toponodes.yml").get("toponodes", []) or []

    def topolink_interfaces(self) -> List[Dict[str, Any]]:
        return self.load_yaml("vars/topology/topolinks.yml").get(
            "topolink_interfaces", []
        ) or []

    def topolinks(self) -> List[Dict[str, Any]]:
        return self.load_yaml("vars/topology/topolinks.yml").get("topolinks", []) or []

    def services(self) -> Dict[str, Any]:
        path = self.root / "vars/services/services.yml"
        if not path.exists():
            return {"edge_interfaces": [], "virtual_networks": []}
        return self.load_yaml("vars/services/services.yml")


def info(message: str) -> None:
    print(message, flush=True)


def slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def ensure_tag(nb: pynetbox.api.Api, name: str) -> Any:
    slug = slugify(name)
    tag = nb.extras.tags.get(slug=slug)
    payload = {"name": name, "slug": slug, "color": "9e9e9e"}
    if tag:
        tag.update(payload)
        return tag
    return nb.extras.tags.create(payload)


def ensure_custom_field_definition(
    nb: pynetbox.api.Api,
    *,
    name: str,
    definition: Dict[str, Any],
    content_type: str,
) -> Any:
    cf_api = nb.extras.custom_fields
    payload: Dict[str, Any] = {
        "name": name,
        "type": definition["type"],
        "content_types": [content_type],
        "object_types": [content_type],
        "required": False,
    }
    if "label" in definition:
        payload["label"] = definition["label"]
    if "description" in definition:
        payload["description"] = definition["description"]
    if "default" in definition:
        payload["default"] = definition["default"]
    if "object_type" in definition:
        payload["related_object_type"] = definition["object_type"]

    cf = cf_api.get(name=name)
    if cf:
        cf.update(payload)
        return cf
    return cf_api.create(payload)


def ensure_site(nb: pynetbox.api.Api, name: str) -> Any:
    slug = slugify(name)
    site = nb.dcim.sites.get(slug=slug)
    payload = {"name": name, "slug": slug}
    if site:
        site.update(payload)
        return site
    return nb.dcim.sites.create(payload)


def ensure_device_role(nb: pynetbox.api.Api, name: str) -> Any:
    slug = slugify(name)
    role = nb.dcim.device_roles.get(slug=slug)
    payload = {"name": name, "slug": slug, "vm_role": False, "color": "9e9e9e"}
    if role:
        role.update(payload)
        return role
    return nb.dcim.device_roles.create(payload)


def ensure_device_custom_fields(nb: pynetbox.api.Api) -> None:
    for name, definition in DEVICE_CUSTOM_FIELDS.items():
        ensure_custom_field_definition(
            nb,
            name=name,
            definition=definition,
            content_type="dcim.device",
        )


def ensure_l2vpn_custom_fields(nb: pynetbox.api.Api) -> None:
    for name, definition in L2VPN_CUSTOM_FIELDS.items():
        ensure_custom_field_definition(
            nb,
            name=name,
            definition=definition,
            content_type="vpn.l2vpn",
        )


def ensure_platform(nb: pynetbox.api.Api, name: str, manufacturer_id: int) -> Any:
    slug = slugify(name)
    platform = nb.dcim.platforms.get(slug=slug)
    payload = {"name": name, "slug": slug, "manufacturer": manufacturer_id}
    if platform:
        platform.update(payload)
        return platform
    return nb.dcim.platforms.create(payload)


def collect_device_types(nb: pynetbox.api.Api, manufacturer_id: int) -> List[Any]:
    return list(nb.dcim.device_types.filter(manufacturer_id=manufacturer_id, limit=0))


def resolve_device_type(device_types: Iterable[Any], model_hint: str) -> Optional[Any]:
    normalized = model_hint.lower()
    for candidate in device_types:
        model = (candidate.model or "").lower()
        if model == normalized or model.startswith(normalized):
            return candidate
    return None


def ensure_device(
    nb: pynetbox.api.Api,
    *,
    name: str,
    device_type_id: int,
    role_id: int,
    platform_id: int,
    site_id: int,
    custom_fields: Dict[str, Any],
    tag_ids: Iterable[int],
) -> Any:
    payload = {
        "name": name,
        "device_type": device_type_id,
        "role": role_id,
        "platform": platform_id,
        "site": site_id,
        "status": "active",
        "tags": list(tag_ids),
        "custom_fields": custom_fields,
    }
    device = nb.dcim.devices.get(name=name)
    if device:
        device.update(payload)
        return nb.dcim.devices.get(id=device.id)
    return nb.dcim.devices.create(payload)


def ensure_interface(
    nb: pynetbox.api.Api,
    *,
    device_id: int,
    name: str,
    iface_type: str,
    description: Optional[str] = None,
    tag_ids: Optional[Iterable[int]] = None,
) -> Any:
    iface = nb.dcim.interfaces.get(device_id=device_id, name=name)
    payload = {
        "device": device_id,
        "name": name,
        "type": iface_type,
        "enabled": True,
    }
    if description:
        payload["description"] = description
    if tag_ids:
        payload["tags"] = list(tag_ids)
    if iface:
        iface.update(payload)
        return nb.dcim.interfaces.get(id=iface.id)
    return nb.dcim.interfaces.create(payload)


def ensure_ipam_address(
    nb: pynetbox.api.Api,
    *,
    address: str,
    vrf_id: Optional[int] = None,
    status: str = "active",
    description: Optional[str] = None,
) -> Any:
    payload: Dict[str, Any] = {
        "address": address,
        "status": status,
    }
    if vrf_id:
        payload["vrf"] = vrf_id
    if description:
        payload["description"] = description

    query: Dict[str, Any] = {"address": address}
    if vrf_id:
        query["vrf_id"] = vrf_id
    ip_obj = nb.ipam.ip_addresses.get(**query)
    if ip_obj:
        ip_obj.update(payload)
        return nb.ipam.ip_addresses.get(id=ip_obj.id)
    return nb.ipam.ip_addresses.create(payload)


def ensure_primary_ip(nb: pynetbox.api.Api, *, device: Any, interface: Any, address: str) -> None:
    cidr = f"{address}/32"
    ip_obj = nb.ipam.ip_addresses.get(address=cidr)
    payload = {
        "address": cidr,
        "status": "active",
        "assigned_object_type": "dcim.interface",
        "assigned_object_id": interface.id,
    }
    if ip_obj:
        ip_obj.update(payload)
    else:
        ip_obj = nb.ipam.ip_addresses.create(payload)
    if not device.primary_ip4 or device.primary_ip4.id != ip_obj.id:
        device.update({"primary_ip4": ip_obj.id})


def ensure_vlan(
    nb: pynetbox.api.Api,
    *,
    site_id: int,
    name: str,
    vid: int,
    tag_ids: Iterable[int],
    description: Optional[str] = None,
) -> Any:
    vlan = nb.ipam.vlans.get(site_id=site_id, vid=vid)
    payload = {
        "name": name,
        "site": site_id,
        "vid": vid,
        "status": "active",
        "tags": list(tag_ids),
    }
    if description:
        payload["description"] = description
    if vlan:
        vlan.update(payload)
        return nb.ipam.vlans.get(id=vlan.id)
    return nb.ipam.vlans.create(payload)


def ensure_vrf(
    nb: pynetbox.api.Api,
    *,
    name: str,
    description: str,
    tag_ids: Iterable[int],
) -> Any:
    vrf = nb.ipam.vrfs.get(name=name)
    payload = {
        "name": name,
        "description": description,
        "tags": list(tag_ids),
    }
    if vrf:
        vrf.update(payload)
        return nb.ipam.vrfs.get(id=vrf.id)
    return nb.ipam.vrfs.create(payload)


def ensure_l2vpn(
    nb: pynetbox.api.Api,
    *,
    name: str,
    identifier: Optional[int],
    description: str,
    tag_ids: Iterable[int],
    custom_fields: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
    if not hasattr(nb, "vpn"):
        return None
    payload = {
        "name": name,
        "slug": slugify(name),
        "type": "vxlan-evpn",
        "status": "active",
        "tags": list(tag_ids),
    }
    if identifier is not None:
        payload["identifier"] = identifier
    if custom_fields:
        payload["custom_fields"] = custom_fields
    l2vpn = nb.vpn.l2vpns.get(name=name)
    if l2vpn:
        l2vpn.update(payload)
        return nb.vpn.l2vpns.get(id=l2vpn.id)
    try:
        return nb.vpn.l2vpns.create(payload)
    except pynetbox.core.query.RequestError as exc:  # pragma: no cover
        if getattr(exc, "error", "").find("/api/vpn/l2vpns") >= 0:
            info("NetBox does not expose the VPN app; skipping L2VPN creation.")
            return None
        raise


def ensure_label_tag(nb: pynetbox.api.Api, *, label: str) -> Any:
    tag = nb.extras.tags.get(name=label)
    if tag:
        return tag
    slug = slugify(label)
    return nb.extras.tags.create({"name": label, "slug": slug, "color": "5e35b1"})


def interface_type_for_speed(speed: Optional[str]) -> str:
    if not speed:
        return FABRIC_INTERFACE_TYPE
    return SPEED_TO_INTERFACE_TYPE.get(speed.upper(), FABRIC_INTERFACE_TYPE)


def create_cable(nb: pynetbox.api.Api, payload: Dict[str, Any]) -> Any:
    url = f"{nb.base_url}/dcim/cables/"
    headers = {
        "Authorization": f"Token {nb.token}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Cable create failed with status {response.status_code}: {response.text}"
        )
    cable_id = response.json().get("id")
    if not cable_id:
        raise RuntimeError("Cable create response missing id field")
    return nb.dcim.cables.get(id=cable_id)


def sanitize_gateway(ip_prefix: str) -> str:
    return ip_prefix.strip()


def parse_edge_interfaces(service_data: Dict[str, Any]) -> List[EdgeInterfaceSpec]:
    results: List[EdgeInterfaceSpec] = []
    for entry in service_data.get("edge_interfaces", []) or []:
        name = entry.get("name")
        if not name:
            continue
        labels = entry.get("labels") or {}
        spec = entry.get("spec") or {}
        members = spec.get("members") or []
        speed = (spec.get("ethernet") or {}).get("speed") or "10G"
        results.append(
            EdgeInterfaceSpec(name=name, labels=labels, members=members, speed=speed)
        )
    return results


def parse_virtual_networks(service_data: Dict[str, Any]) -> List[VirtualNetworkSpec]:
    results: List[VirtualNetworkSpec] = []
    for entry in service_data.get("virtual_networks", []) or []:
        name = entry.get("name")
        if not name:
            continue
        namespace = entry.get("namespace") or "eda"
        spec = entry.get("spec") or {}
        routers = spec.get("routers") or []
        bridge_domains_raw = spec.get("bridgeDomains") or []
        irb_lookup: Dict[str, str] = {}
        for irb in spec.get("irbInterfaces") or []:
            irb_spec = irb.get("spec") or {}
            bridge_domain = irb_spec.get("bridgeDomain")
            if not bridge_domain:
                continue
            for ip_def in irb_spec.get("ipAddresses") or []:
                ipv4 = (ip_def.get("ipv4Address") or {}).get("ipPrefix")
                if ipv4:
                    irb_lookup[bridge_domain] = sanitize_gateway(ipv4)
                    break
        bridge_domains: List[BridgeDomainSpec] = []
        for bd in bridge_domains_raw:
            bd_name = bd.get("name")
            if not bd_name:
                continue
            bridge_domains.append(
                BridgeDomainSpec(
                    name=bd_name,
                    source_spec=bd.get("spec") or {},
                    gateway=irb_lookup.get(bd_name),
                )
            )
        vlans = spec.get("vlans") or []
        results.append(
            VirtualNetworkSpec(
                name=name,
                namespace=namespace,
                routers=routers,
                bridge_domains=bridge_domains,
                vlans=vlans,
            )
        )
    return results


def ensure_services(
    nb: pynetbox.api.Api,
    *,
    site_id: int,
    tag_ids: Iterable[int],
    edge_tag_id: int,
    label_tag_cache: Dict[str, Any],
    edge_specs: List[EdgeInterfaceSpec],
    vnets: List[VirtualNetworkSpec],
    interface_cache: Dict[str, Dict[str, Any]],
    devices: Dict[str, Any],
) -> None:
    vlan_lookup: Dict[str, Any] = {}

    for vnet in vnets:
        router_names = [router.get("name") for router in vnet.routers if router.get("name")]
        router_names = [name for name in router_names if name]
        vrf = None
        if router_names:
            vrf_description = f"EDA demo VRF {vnet.name}"
            vrf = ensure_vrf(
                nb,
                name=vnet.name,
                description=vrf_description,
                tag_ids=tag_ids,
            )
            info(f"Ensured VRF {vrf.name} (id={vrf.id}).")

        bridge_domain_metadata: Dict[str, BridgeDomainSpec] = {
            bd.name: bd for bd in vnet.bridge_domains
        }

        for vlan_def in vnet.vlans:
            vlan_name = vlan_def.get("name")
            vlan_spec = vlan_def.get("spec") or {}
            vlan_id_raw = vlan_spec.get("vlanID")
            if vlan_name and vlan_id_raw is not None:
                try:
                    vlan_id = int(str(vlan_id_raw))
                except ValueError:
                    continue
                vlan_obj = ensure_vlan(
                    nb,
                    site_id=site_id,
                    name=vlan_name,
                    vid=vlan_id,
                    tag_ids=tag_ids,
                    description=f"EDA demo VLAN {vlan_name}",
                )
                vlan_lookup[vlan_name] = vlan_obj

        for bd_name, bd in bridge_domain_metadata.items():
            l2_identifier = None
            vlan_def = next((v for v in vnet.vlans if v.get("spec", {}).get("bridgeDomain") == bd_name), None)
            if vlan_def:
                try:
                    l2_identifier = int(str(vlan_def.get("spec", {}).get("vlanID")))
                except (TypeError, ValueError):
                    l2_identifier = None
            custom_fields: Dict[str, Any] = {
                "L2vpn_bridge_domain_spec": bd.source_spec,
            }
            if bd.gateway:
                ip_obj = ensure_ipam_address(
                    nb,
                    address=bd.gateway,
                    vrf_id=vrf.id if vrf else None,
                    description=f"EDA gateway for {bd_name}",
                )
                custom_fields["L2vpn_gateway"] = ip_obj.id
            if vrf:
                custom_fields["L2vpn_ipvrf"] = vrf.id
            l2vpn = ensure_l2vpn(
                nb,
                name=bd_name,
                identifier=l2_identifier,
                description=f"EDA demo bridge domain {bd_name}",
                tag_ids=tag_ids,
                custom_fields=custom_fields or None,
            )
            if l2vpn:
                info(f"Ensured L2VPN {l2vpn.name} (id={l2vpn.id}).")

    for edge in edge_specs:
        label_objects: List[Any] = []
        for label_key, label_value in edge.labels.items():
            if str(label_value).lower() != "true":
                continue
            tag = label_tag_cache.get(label_key)
            if not tag:
                tag = ensure_label_tag(nb, label=label_key)
                label_tag_cache[label_key] = tag
            label_objects.append(tag)
        vlan_ids: List[int] = []
        for label_key in edge.labels.keys():
            if not label_key.startswith("eda.nokia.com/macvrf"):
                continue
            suffix = label_key.split("/")[-1]
            try:
                vlan_id = int(str(suffix).replace("macvrf", ""))
            except ValueError:
                continue
            vlan_obj = ensure_vlan(
                nb,
                site_id=site_id,
                name=suffix,
                vid=vlan_id,
                tag_ids=tag_ids,
                description=f"EDA VLAN {suffix}",
            )
            vlan_lookup[suffix] = vlan_obj
            vlan_ids.append(vlan_obj.id)

        for member in edge.members:
            node = member.get("node")
            iface_name = member.get("interface")
            if not node or not iface_name:
                continue
            iface = interface_cache.get(node, {}).get(iface_name)
            if not iface:
                device_obj = devices.get(node)
                if not device_obj:
                    info(f"Edge member skipped: device {node} not present in NetBox.")
                    continue
                info(
                    f"Creating edge interface {node} {iface_name} for service member {edge.name}."
                )
                new_iface = ensure_interface(
                    nb,
                    device_id=device_obj.id,
                    name=iface_name,
                    iface_type=interface_type_for_speed(edge.speed),
                    description=edge.name,
                    tag_ids=list({edge_tag_id, *tag_ids}),
                )
                interface_cache.setdefault(node, {})[iface_name] = new_iface
                iface = new_iface
            desired_type = interface_type_for_speed(edge.speed)
            current_type = getattr(getattr(iface, "type", None), "value", None)
            if current_type != desired_type:
                iface.update({"type": desired_type})
                iface = nb.dcim.interfaces.get(id=iface.id)
                interface_cache[node][iface_name] = iface
            existing_tag_ids = {
                tag.id
                for tag in getattr(iface, "tags", [])
                if getattr(tag, "id", None) is not None
            }
            edge_tag_ids = {tag.id for tag in label_objects}
            desired_tag_ids = existing_tag_ids | edge_tag_ids | {edge_tag_id}
            payload = {"tags": sorted(desired_tag_ids)}
            if vlan_ids:
                payload["mode"] = "tagged"
                payload["tagged_vlans"] = sorted(set(vlan_ids))
            iface.update(payload)
            interface_cache[node][iface_name] = nb.dcim.interfaces.get(id=iface.id)


def main() -> int:
    netbox_url = os.environ.get("NETBOX_URL", "http://127.0.0.1:8000")
    token = os.environ.get("NETBOX_TOKEN")

    if not token:
        print("NETBOX_TOKEN is required", file=sys.stderr)
        return 1

    info(f"Connecting to NetBox at {netbox_url}...")
    nb = pynetbox.api(netbox_url, token=token)

    loader = TopologyLoader(BASE_DIR)
    toponodes = loader.toponodes()
    topolink_iface_groups = loader.topolink_interfaces()
    topolink_groups = loader.topolinks()
    services = loader.services()

    info(
        f"Loaded {len(toponodes)} nodes, {len(topolink_iface_groups)} interface groups, "
        f"and {len(topolink_groups)} link groups."
    )

    ensure_device_custom_fields(nb)
    ensure_l2vpn_custom_fields(nb)

    site = ensure_site(nb, DEFAULT_SITE_NAME)
    demo_tag = ensure_tag(nb, DEFAULT_TAG_NAME)
    edge_tag = ensure_tag(nb, EDGE_TAG_NAME)
    isl_tag = ensure_tag(nb, ISL_TAG_NAME)

    manufacturer = nb.dcim.manufacturers.get(name="Nokia")
    if not manufacturer:
        manufacturer = nb.dcim.manufacturers.create({"name": "Nokia", "slug": "nokia"})

    device_types = collect_device_types(nb, manufacturer.id)

    platforms: Dict[str, Any] = {}
    devices: Dict[str, Any] = {}
    interface_cache: Dict[str, Dict[str, Any]] = {}

    for node in toponodes:
        platform_name = node.get("platform") or "SR Linux"
        platform = platforms.get(platform_name)
        if not platform:
            platform = ensure_platform(nb, platform_name, manufacturer.id)
            platforms[platform_name] = platform

        device_type = resolve_device_type(device_types, platform_name)
        if not device_type:
            print(
                f"Skipped node {node.get('name')} because device type '{platform_name}' is missing in NetBox.",
                file=sys.stderr,
            )
            continue

        role_name = node.get("role") or "leaf"
        role = ensure_device_role(nb, role_name)

        node_cf = {
            "operatingSystem": node.get("operating_system") or "srl",
            "version": node.get("version") or "25.7",
            "onBoarded": bool(node.get("on_boarded", False)),
        }
        if node.get("node_profile"):
            node_cf["nodeProfile"] = node["node_profile"]

        device = ensure_device(
            nb,
            name=node["name"],
            device_type_id=device_type.id,
            role_id=role.id,
            platform_id=platform.id,
            site_id=site.id,
            custom_fields=node_cf,
            tag_ids=[demo_tag.id],
        )
        devices[node["name"]] = device

        mgmt_iface = ensure_interface(
            nb,
            device_id=device.id,
            name="mgmt0",
            iface_type=MGMT_INTERFACE_TYPE,
            description="Management",
        )
        interface_cache.setdefault(device.name, {})["mgmt0"] = mgmt_iface

        prod_ip = node.get("production_ipv4")
        if prod_ip:
            ensure_primary_ip(nb, device=device, interface=mgmt_iface, address=prod_ip)

    for group in topolink_iface_groups:
        description = group.get("description")
        for member in group.get("members") or []:
            node_name = member.get("node")
            iface_name = member.get("interface")
            if node_name not in devices or not iface_name:
                continue
            device = devices[node_name]
            iface = ensure_interface(
                nb,
                device_id=device.id,
                name=iface_name,
                iface_type=FABRIC_INTERFACE_TYPE,
                description=description,
                tag_ids=[demo_tag.id],
            )
            interface_cache.setdefault(node_name, {})[iface_name] = iface

    info("Refreshing demo cables (removing existing ones tagged for the demo)...")
    for cable in nb.dcim.cables.filter(tag=demo_tag.slug, limit=0):
        cable.delete()

    total_links = 0
    for group in topolink_groups:
        group_name = group.get("name") or "link-group"
        for link in group.get("links") or []:
            total_links += 1
            local = link.get("local") or {}
            remote = link.get("remote") or {}
            local_device = devices.get(local.get("node"))
            remote_device = devices.get(remote.get("node"))
            if not local_device or not remote_device:
                continue
            local_iface = interface_cache.get(local_device.name, {}).get(
                local.get("interface")
            )
            remote_iface = interface_cache.get(remote_device.name, {}).get(
                remote.get("interface")
            )
            if not local_iface or not remote_iface:
                continue
            speed = link.get("speed")
            iface_type = interface_type_for_speed(speed)
            local_type_value = getattr(getattr(local_iface, "type", None), "value", None)
            if iface_type != local_type_value:
                local_iface.update({"type": iface_type})
                local_iface = nb.dcim.interfaces.get(id=local_iface.id)
                interface_cache[local_device.name][local_iface.name] = local_iface
            remote_type_value = getattr(getattr(remote_iface, "type", None), "value", None)
            if iface_type != remote_type_value:
                remote_iface.update({"type": iface_type})
                remote_iface = nb.dcim.interfaces.get(id=remote_iface.id)
                interface_cache[remote_device.name][remote_iface.name] = remote_iface
            payload = {
                "label": group_name,
                "status": "connected",
                "type": "smf",
                "tags": [demo_tag.id, isl_tag.id],
                "termination_a_type": "dcim.interface",
                "termination_a_id": local_iface.id,
                "termination_b_type": "dcim.interface",
                "termination_b_id": remote_iface.id,
                "a_terminations": [
                    {"object_type": "dcim.interface", "object_id": local_iface.id}
                ],
                "b_terminations": [
                    {"object_type": "dcim.interface", "object_id": remote_iface.id}
                ],
            }
            info(
                f"Creating cable '{group_name}' between {local_device.name} {local_iface.name} "
                f"and {remote_device.name} {remote_iface.name}"
            )
            try:
                cable = create_cable(nb, payload)
                info(
                    f"Linked {local_device.name} {local_iface.name} <-> "
                    f"{remote_device.name} {remote_iface.name} as {cable.label} (id={cable.id})"
                )
            except Exception as exc:  # pragma: no cover - runtime guard
                print(
                    "Failed to create cable between",
                    local_device.name,
                    local_iface.name,
                    "and",
                    remote_device.name,
                    remote_iface.name,
                    ":",
                    exc,
                    "\nPayload:",
                    json.dumps(payload, indent=2),
                    file=sys.stderr,
                )
                raise

    info(f"Ensured {total_links} physical links.")

    edge_specs = parse_edge_interfaces(services)
    vnet_specs = parse_virtual_networks(services)

    label_tag_cache: Dict[str, Any] = {}
    ensure_services(
        nb,
        site_id=site.id,
        tag_ids=[demo_tag.id],
        edge_tag_id=edge_tag.id,
        label_tag_cache=label_tag_cache,
        edge_specs=edge_specs,
        vnets=vnet_specs,
        interface_cache=interface_cache,
        devices=devices,
    )

    info("NetBox population complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
