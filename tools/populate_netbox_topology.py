#!/usr/bin/env python3
"""Populate NetBox with topology data derived from the local YAML vars.

The script creates device roles, platforms, devices, interfaces, cables, and
config contexts that mirror the demo topology stored under vars/topology.

Expected environment variables:
  NETBOX_URL   - base URL of the NetBox instance (e.g. http://127.0.0.1/)
  NETBOX_TOKEN - API token with write permission.
"""

from __future__ import annotations

import ipaddress
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

import pynetbox
from pynetbox.core.query import RequestError
import yaml
import requests

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SITE_NAME = "EDA Demo"
DEFAULT_TAG_NAME = "eda-demo-topology"
ISL_TAG_NAME = "ISL"
EDGE_TAG_NAME = "EDA Edge"
EDGE_LAG_CF_NAME = "edaEdgeLagId"
VRF_SPEC_CF_NAME = "edaVrfSpec"
BD_SPEC_CF_NAME = "edaBridgeDomainSpec"
BD_PARENT_VRF_CF_NAME = "edaParentIpVrf"
BD_GATEWAY_IP_CF_NAME = "edaGatewayIp"


def info(message: str) -> None:
    print(message, flush=True)


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def ensure_site(nb: pynetbox.api.Api, name: str) -> Any:
    slug = slugify(name)
    site = nb.dcim.sites.get(slug=slug)
    payload = {"name": name, "slug": slug}
    if site:
        site.update(payload)
        return site
    return nb.dcim.sites.create(payload)


def ensure_device_role(nb: pynetbox.api.Api, name: str, color: str) -> Any:
    slug = slugify(name)
    role = nb.dcim.device_roles.get(slug=slug)
    payload = {"name": name, "slug": slug, "color": color, "vm_role": False}
    if role:
        role.update(payload)
        return role
    return nb.dcim.device_roles.create(payload)


def ensure_platform(
    nb: pynetbox.api.Api, name: str, manufacturer_id: int | None = None
) -> Any:
    slug = slugify(name)
    platform = nb.dcim.platforms.get(slug=slug)
    payload: Dict[str, Any] = {"name": name, "slug": slug}
    if manufacturer_id:
        payload["manufacturer"] = manufacturer_id
    if platform:
        platform.update(payload)
        return platform
    return nb.dcim.platforms.create(payload)


def ensure_tag(nb: pynetbox.api.Api, name: str) -> Any:
    slug = slugify(name)
    tag = nb.extras.tags.get(slug=slug)
    payload = {"name": name, "slug": slug, "color": "9e9e9e"}
    if tag:
        tag.update(payload)
        return tag
    return nb.extras.tags.create(payload)


def ensure_vlan(
    nb: pynetbox.api.Api,
    *,
    site_id: int,
    name: str,
    vid: int,
    status: str = "active",
    description: str | None = None,
    tag_ids: Iterable[int] | None = None,
) -> Any:
    vlan = nb.ipam.vlans.get(site_id=site_id, vid=vid)
    payload: Dict[str, Any] = {
        "name": name,
        "vid": vid,
        "site": site_id,
        "status": status,
    }
    if description:
        payload["description"] = description
    if tag_ids:
        payload["tags"] = list(tag_ids)
    if vlan:
        vlan.update(payload)
        return nb.ipam.vlans.get(id=vlan.id)
    return nb.ipam.vlans.create(payload)


def ensure_l2vpn(
    nb: pynetbox.api.Api,
    *,
    name: str,
    type_slug: str = "vxlan-evpn",
    description: str | None = None,
    status: str = "active",
    identifier: int | None = None,
    tag_ids: Iterable[int] | None = None,
    custom_fields: Dict[str, Any] | None = None,
) -> Any | None:
    if not hasattr(nb, "vpn"):
        return None
    slug = slugify(name)
    try:
        l2vpn = nb.vpn.l2vpns.get(slug=slug)
    except RequestError as exc:
        if getattr(exc, "req", None) is not None and exc.req.status_code == 404:
            return None
        raise
    payload: Dict[str, Any] = {
        "name": name,
        "slug": slug,
        "type": type_slug,
        "status": status,
    }
    if identifier is not None:
        payload["identifier"] = identifier
    if description:
        payload["description"] = description
    if tag_ids:
        payload["tags"] = list(tag_ids)
    if custom_fields:
        payload["custom_fields"] = custom_fields
    if l2vpn:
        l2vpn.update(payload)
        return nb.vpn.l2vpns.get(id=l2vpn.id)
    try:
        return nb.vpn.l2vpns.create(payload)
    except RequestError as exc:
        if getattr(exc, "req", None) is not None and exc.req.status_code == 404:
            return None
        raise


def ensure_vrf(
    nb: pynetbox.api.Api,
    *,
    name: str,
    rd: str | None = None,
    description: str | None = None,
    tag_ids: Iterable[int] | None = None,
    custom_fields: Dict[str, Any] | None = None,
) -> Any:
    """Ensure an IP VRF exists."""

    vrf = nb.ipam.vrfs.get(name=name)
    payload: Dict[str, Any] = {
        "name": name,
    }
    if rd:
        payload["rd"] = rd
    if description:
        payload["description"] = description
    if tag_ids:
        payload["tags"] = list(tag_ids)
    if custom_fields:
        payload["custom_fields"] = custom_fields
    if vrf:
        vrf.update(payload)
        return nb.ipam.vrfs.get(id=vrf.id)
    return nb.ipam.vrfs.create(payload)


def ensure_custom_field(
    nb: pynetbox.api.Api,
    *,
    name: str,
    field_type: str,
    content_types: Iterable[str],
    label: str | None = None,
    description: str | None = None,
    default: Any | None = None,
) -> Any:
    """Ensure a custom field exists for the provided NetBox content types."""

    content_type_list = list(content_types)
    cf = nb.extras.custom_fields.get(name=name)
    payload: Dict[str, Any] = {
        "name": name,
        "type": field_type,
        "content_types": content_type_list,
        "object_types": content_type_list,
        "required": False,
    }
    if label is not None:
        payload["label"] = label
    if description is not None:
        payload["description"] = description
    if default is not None:
        payload["default"] = default

    if cf:
        cf.update(payload)
        return cf
    return nb.extras.custom_fields.create(payload)


def ensure_device_custom_field(
    nb: pynetbox.api.Api,
    *,
    name: str,
    field_type: str,
    label: str | None = None,
    description: str | None = None,
    default: Any | None = None,
) -> Any:
    """Ensure a custom field exists on dcim.device objects."""

    return ensure_custom_field(
        nb,
        name=name,
        field_type=field_type,
        content_types=["dcim.device"],
        label=label,
        description=description,
        default=default,
    )


def ensure_interface_custom_field(
    nb: pynetbox.api.Api,
    *,
    name: str,
    field_type: str,
    label: str | None = None,
    description: str | None = None,
    default: Any | None = None,
) -> Any:
    """Ensure a custom field exists on dcim.interface objects."""

    return ensure_custom_field(
        nb,
        name=name,
        field_type=field_type,
        content_types=["dcim.interface"],
        label=label,
        description=description,
        default=default,
    )


def ensure_device(
    nb: pynetbox.api.Api,
    *,
    name: str,
    device_type_id: int,
    role_id: int,
    site_id: int,
    platform_id: int | None,
    tag_ids: Iterable[int],
    custom_fields: Dict[str, Any] | None = None,
) -> Any:
    device = nb.dcim.devices.get(name=name)
    payload: Dict[str, Any] = {
        "name": name,
        "device_type": device_type_id,
        "role": role_id,
        "site": site_id,
        "status": "active",
        "tags": list(tag_ids),
    }
    if platform_id:
        payload["platform"] = platform_id
    if custom_fields:
        payload["custom_fields"] = custom_fields
    if device:
        device.update(payload)
        return nb.dcim.devices.get(name=name)
    return nb.dcim.devices.create(payload)


def ensure_interface(
    nb: pynetbox.api.Api,
    *,
    device_id: int,
    name: str,
    type_slug: str,
    description: str | None = None,
    tag_id: int | None = None,
) -> Any:
    iface = nb.dcim.interfaces.get(device_id=device_id, name=name)
    payload: Dict[str, Any] = {
        "device": device_id,
        "name": name,
        "type": type_slug,
        "enabled": True,
    }
    if description:
        payload["description"] = description
    if tag_id:
        payload["tags"] = [tag_id]
    if iface:
        iface.update(payload)
        return iface
    return nb.dcim.interfaces.create(payload)


def ensure_primary_ip(
    nb: pynetbox.api.Api, *, device: Any, interface: Any, address: str
) -> Any:
    cidr = f"{ipaddress.ip_address(address)}/32"
    ip_obj = nb.ipam.ip_addresses.get(address=cidr)
    payload: Dict[str, Any] = {
        "address": cidr,
        "status": "active",
        "assigned_object_type": "dcim.interface",
        "assigned_object_id": interface.id,
    }
    if ip_obj:
        if ip_obj.assigned_object_id != interface.id:
            ip_obj.update(payload)
    else:
        ip_obj = nb.ipam.ip_addresses.create(payload)
    if not device.primary_ip4 or device.primary_ip4.id != ip_obj.id:
        device.update({"primary_ip4": ip_obj.id})
    return ip_obj


def ensure_ipam_address(
    nb: pynetbox.api.Api,
    *,
    address: str,
    vrf_id: int | None = None,
    status: str = "active",
    role: str | None = None,
    description: str | None = None,
) -> Any:
    payload: Dict[str, Any] = {
        "address": address,
        "status": status,
    }
    if vrf_id:
        payload["vrf"] = vrf_id
    if role:
        payload["role"] = role
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


def ensure_cable(
    nb: pynetbox.api.Api,
    *,
    name: str,
    a_iface: Any,
    b_iface: Any,
    cable_type: str,
    tag_ids: Iterable[int],
) -> Any:
    existing = nb.dcim.cables.get(label=name)
    if existing:
        existing.delete()

    payload = {
        "label": name,
        "status": "connected",
        "type": cable_type,
        "a_terminations": [
            {"object_type": "dcim.interface", "object_id": a_iface.id},
        ],
        "b_terminations": [
            {"object_type": "dcim.interface", "object_id": b_iface.id},
        ],
        "tags": list(tag_ids),
    }

    headers = {
        "Authorization": f"Token {nb.token}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        f"{nb.base_url}/dcim/cables/",
        headers=headers,
        json=payload,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to create cable '{name}': {response.status_code} {response.text}"
        )
    cable_id = response.json().get("id")
    return nb.dcim.cables.get(cable_id)


def main() -> int:
    netbox_url = os.environ.get("NETBOX_URL", "http://100.82.85.165/")
    token = os.environ.get("NETBOX_TOKEN")
    if not token:
        print("NETBOX_TOKEN is required", file=sys.stderr)
        return 1

    info(f"Connecting to NetBox at {netbox_url}...")
    nb = pynetbox.api(netbox_url, token=token)
    info("NetBox API client initialized.")

    info("Loading topology definitions from local YAML files...")
    toponodes = load_yaml(BASE_DIR / "vars/topology/toponodes.yml")["toponodes"]
    topology_links = load_yaml(BASE_DIR / "vars/topology/topolinks.yml")
    services_file = BASE_DIR / "vars/services/services.yml"
    services_data: Dict[str, Any] = {}
    if services_file.exists():
        services_data = load_yaml(services_file) or {}
        info(f"Loaded services definitions from {services_file}.")
    else:
        info("No services file found; continuing without services definitions.")
    service_edge_interfaces: List[Dict[str, Any]] = (
        services_data.get("edge_interfaces") or []
    )
    service_virtual_networks: List[Dict[str, Any]] = (
        services_data.get("virtual_networks") or []
    )
    topolink_groups = topology_links.get("topolinks", [])
    interface_groups = topology_links.get("topolink_interfaces", [])
    total_toponodes = len(toponodes)
    info(
        f"Loaded {total_toponodes} toponodes, {len(topolink_groups)} link groups, and {len(interface_groups)} interface groups."
    )
    info(
        f"Edge interface definitions: {len(service_edge_interfaces)}; virtual networks: {len(service_virtual_networks)}."
    )

    info("Ensuring required custom fields in NetBox...")
    # Ensure device custom fields required by the NetBox integration exist.
    ensure_device_custom_field(
        nb,
        name="operatingSystem",
        field_type="text",
        label="Operating System",
        description="Operating system reported to Nokia EDA",
    )
    ensure_device_custom_field(
        nb,
        name="version",
        field_type="text",
        label="Software Version",
        description="Software version reported to Nokia EDA",
    )
    ensure_device_custom_field(
        nb,
        name="onBoarded",
        field_type="boolean",
        label="On-boarded",
        description="Whether the node has been onboarded into Nokia EDA",
        default=False,
    )
    ensure_device_custom_field(
        nb,
        name="nodeProfile",
        field_type="text",
        label="Node Profile",
        description="Nokia EDA NodeProfile name referenced by the device",
    )

    ensure_interface_custom_field(
        nb,
        name=EDGE_LAG_CF_NAME,
        field_type="text",
        label="Edge LAG Identifier",
        description="Identifier used to group multihomed edge interfaces",
    )
    ensure_custom_field(
        nb,
        name=VRF_SPEC_CF_NAME,
        field_type="json",
        content_types=["ipam.vrf"],
        label="EDA VRF Spec",
        description="Router spec captured from Nokia EDA virtual network definitions",
    )
    ensure_custom_field(
        nb,
        name=BD_SPEC_CF_NAME,
        field_type="json",
        content_types=["vpn.l2vpn"],
        label="EDA Bridge Domain Spec",
        description="Bridge domain spec captured from Nokia EDA virtual network definitions",
    )
    ensure_custom_field(
        nb,
        name=BD_PARENT_VRF_CF_NAME,
        field_type="text",
        content_types=["vpn.l2vpn"],
        label="EDA Parent IP VRF",
        description="Name of the IP VRF associated with this bridge domain",
    )
    ensure_custom_field(
        nb,
        name=BD_GATEWAY_IP_CF_NAME,
        field_type="text",
        content_types=["vpn.l2vpn"],
        label="EDA Gateway IPv4",
        description="Gateway IPv4 prefix associated with this MAC VRF",
    )
    info("Custom fields ensured.")

    # Pre-load manufacturer lookup.
    info("Ensuring manufacturer and loading device types...")
    manufacturer = nb.dcim.manufacturers.get(name="Nokia")
    if not manufacturer:
        manufacturer = nb.dcim.manufacturers.create({"name": "Nokia", "slug": "nokia"})

    device_types = list(nb.dcim.device_types.filter(manufacturer_id=manufacturer.id))
    info(
        f"Discovered {len(device_types)} device types for manufacturer {manufacturer.name}."
    )

    def resolve_device_type(model_name: str) -> Any | None:
        for candidate in device_types:
            if candidate.model.lower().startswith(model_name.lower()):
                return candidate
        return None

    info(f"Ensuring site '{DEFAULT_SITE_NAME}' and topology tags...")
    site = ensure_site(nb, DEFAULT_SITE_NAME)
    tag = ensure_tag(nb, DEFAULT_TAG_NAME)
    isl_tag = ensure_tag(nb, ISL_TAG_NAME)
    edge_tag = ensure_tag(nb, EDGE_TAG_NAME)
    label_tag_cache: Dict[str, Any] = {}
    info("Site and tags ensured.")

    # Remove legacy config contexts left by earlier demos.
    for ctx in nb.extras.config_contexts.filter(name="EDA Demo Services"):
        info("Removing legacy 'EDA Demo Services' config context...")
        ctx.delete()
    for ctx in nb.extras.config_contexts.filter(limit=0):
        if ctx.name.endswith("-node-profile"):
            info(f"Removing legacy config context '{ctx.name}'...")
            ctx.delete()
    info("Legacy config contexts removed (if present).")

    vrf_lookup: Dict[str, Any] = {}
    l2vpn_lookup: Dict[str, Any] = {}
    vlan_lookup: Dict[str, Any] = {}
    irb_ip_addresses_ensured = 0

    l2vpn_supported = True

    if service_virtual_networks:
        info(f"Processing {len(service_virtual_networks)} service virtual networks...")
    else:
        info(
            "No service virtual networks defined; skipping L2VPN/VLAN provisioning from services metadata."
        )

    for virtual_network in service_virtual_networks:
        vnet_name = virtual_network.get("name")
        if not vnet_name:
            continue
        vnet_spec = virtual_network.get("spec", {}) or {}
        vlan_defs = vnet_spec.get("vlans", []) or []
        bridge_domains = vnet_spec.get("bridgeDomains", []) or []
        router_defs = vnet_spec.get("routers", []) or []
        vnet_namespace = virtual_network.get("namespace") or "eda"
        vnet_irb_interfaces = vnet_spec.get("irbInterfaces", []) or []
        bd_gateway_lookup: Dict[str, str] = {}
        router_names: List[str] = []
        for router_def in router_defs:
            router_name = router_def.get("name")
            if not router_name:
                continue
            router_spec = router_def.get("spec", {}) or {}
            if router_name not in router_names:
                router_names.append(router_name)
            rd_candidate = router_spec.get("rd") or router_spec.get("routeDistinguisher")
            if rd_candidate is None:
                rd_candidate = router_spec.get("routerID")
            rd_value: str | None = None
            if rd_candidate is not None:
                rd_candidate_str = str(rd_candidate)
                if ":" in rd_candidate_str:
                    rd_value = rd_candidate_str
            vrf_custom_fields = {VRF_SPEC_CF_NAME: {"namespace": vnet_namespace}}
            vrf_description = f"EDA demo IP VRF {router_name} ({vnet_name})"
            vrf = ensure_vrf(
                nb,
                name=router_name,
                rd=rd_value,
                description=vrf_description,
                tag_ids=[tag.id],
                custom_fields=vrf_custom_fields,
            )
            vrf_lookup[router_name] = vrf

        for irb_def in vnet_irb_interfaces:
            irb_name = irb_def.get("name")
            irb_spec = irb_def.get("spec", {}) or {}
            bridge_domain_name = irb_spec.get("bridgeDomain")
            if not bridge_domain_name:
                continue
            router_name = irb_spec.get("router")
            ip_mtu = irb_spec.get("ipMTU")
            ip_entries: List[Dict[str, Any]] = []
            preferred_ipv4: str | None = None
            for address_def in irb_spec.get("ipAddresses", []):
                ip_payload = address_def.get("ipv4Address") or address_def.get("ipv6Address")
                if not ip_payload:
                    continue
                ip_prefix = ip_payload.get("ipPrefix")
                if not ip_prefix:
                    continue
                is_ipv6 = ":" in ip_prefix
                vrf_obj = vrf_lookup.get(router_name) if router_name else None
                vrf_id = getattr(vrf_obj, "id", None) if vrf_obj else None
                ip_description = f"IRB {irb_name or bridge_domain_name} ({router_name or vnet_name})"
                ip_obj = ensure_ipam_address(
                    nb,
                    address=ip_prefix,
                    vrf_id=vrf_id,
                    description=ip_description,
                )
                irb_ip_addresses_ensured += 1
                ip_entry: Dict[str, Any] = {
                    "address": ip_prefix,
                    "primary": bool(ip_payload.get("primary")),
                }
                if ip_obj:
                    ip_entry["ipId"] = ip_obj.id
                ip_entry["family"] = "ipv6" if is_ipv6 else "ipv4"
                ip_entries.append(ip_entry)

                if not is_ipv6:
                    if ip_payload.get("primary"):
                        preferred_ipv4 = ip_prefix
                    elif preferred_ipv4 is None:
                        preferred_ipv4 = ip_prefix

            irb_entry = {
                "name": irb_name or f"{bridge_domain_name}-irb",
                "bridgeDomain": bridge_domain_name,
                "router": router_name or (router_names[0] if router_names else None),
                "ipMTU": ip_mtu,
                "ipAddresses": ip_entries,
            }
            if preferred_ipv4:
                bd_gateway_lookup[bridge_domain_name] = preferred_ipv4

        bridge_domain_vlan_map: Dict[str, int] = {}
        first_vlan: int | None = None
        for vlan_def in vlan_defs:
            vlan_name = vlan_def.get("name")
            vlan_spec = vlan_def.get("spec", {})
            vlan_id_raw = vlan_spec.get("vlanID")
            if not vlan_name or vlan_id_raw is None:
                continue
            try:
                vlan_id = int(str(vlan_id_raw))
            except (TypeError, ValueError):
                continue
            if first_vlan is None:
                first_vlan = vlan_id
            bridge_domain_name = vlan_spec.get("bridgeDomain")
            if bridge_domain_name and bridge_domain_name not in bridge_domain_vlan_map:
                bridge_domain_vlan_map[str(bridge_domain_name)] = vlan_id
            vlan_description = f"EDA demo VLAN {vlan_name} for {vnet_name}"
            if bridge_domain_name:
                vlan_description = (
                    f"EDA demo VLAN {vlan_name} for bridge domain {bridge_domain_name}"
                )
            vlan_obj = ensure_vlan(
                nb,
                site_id=site.id,
                name=vlan_name,
                vid=vlan_id,
                description=vlan_description,
                tag_ids=[tag.id],
            )
            vlan_lookup[vlan_name] = vlan_obj

        # For legacy data without bridge domains, maintain a virtual-network L2VPN.
        if not bridge_domains:
            l2vpn = ensure_l2vpn(
                nb,
                name=vnet_name,
                type_slug="vxlan-evpn",
                description=f"EDA demo virtual network {vnet_name}",
                identifier=first_vlan,
                tag_ids=[tag.id],
            )
            if l2vpn is None:
                l2vpn_supported = False
            else:
                l2vpn_lookup[vnet_name] = l2vpn

        parent_vrf_string = ", ".join(router_names)
        for bridge_domain in bridge_domains:
            bd_name = bridge_domain.get("name")
            if not bd_name:
                continue
            bd_spec = bridge_domain.get("spec", {}) or {}
            identifier = bridge_domain_vlan_map.get(str(bd_name))
            bd_description = f"EDA demo bridge domain {bd_name} ({vnet_name})"
            bd_custom_fields = {BD_SPEC_CF_NAME: bd_spec}
            if parent_vrf_string:
                bd_custom_fields[BD_PARENT_VRF_CF_NAME] = parent_vrf_string
            else:
                bd_custom_fields[BD_PARENT_VRF_CF_NAME] = None
            gateway_ip = bd_gateway_lookup.get(bd_name)
            if gateway_ip:
                bd_custom_fields[BD_GATEWAY_IP_CF_NAME] = gateway_ip
            l2vpn = ensure_l2vpn(
                nb,
                name=bd_name,
                type_slug="vxlan-evpn",
                description=bd_description,
                identifier=identifier,
                tag_ids=[tag.id],
                custom_fields=bd_custom_fields,
            )
            if l2vpn is None:
                l2vpn_supported = False
                continue
            l2vpn_lookup[bd_name] = l2vpn

    def ensure_vlan_from_label(label_key: str) -> Any | None:
        if not label_key.startswith("eda.nokia.com/macvrf"):
            return None
        suffix = label_key.split("/")[-1]
        if suffix in vlan_lookup:
            return vlan_lookup[suffix]
        vlan_id_fragment = suffix.replace("macvrf", "")
        try:
            vlan_id = int(vlan_id_fragment)
        except ValueError:
            return None
        vlan_obj = ensure_vlan(
            nb,
            site_id=site.id,
            name=suffix,
            vid=vlan_id,
            description=f"EDA demo VLAN derived from label {suffix}",
            tag_ids=[tag.id],
        )
        vlan_lookup[suffix] = vlan_obj
        return vlan_obj

    if service_edge_interfaces:
        info(
            f"Deriving VLANs from {len(service_edge_interfaces)} edge interface label definitions..."
        )
    else:
        info("No edge interface label definitions to derive VLANs from.")
    for edge_def in service_edge_interfaces:
        for label_key, label_value in edge_def.get("labels", {}).items():
            if str(label_value).lower() != "true":
                continue
            ensure_vlan_from_label(label_key)

    # Clean up existing demo cables to ensure idempotency.
    info(f"Removing existing demo cables tagged '{tag.slug}'...")
    for cable in nb.dcim.cables.filter(tag=tag.slug, limit=0):
        cable.delete()
    info("Existing demo cables removed.")

    role_colors = defaultdict(lambda: "9e9e9e")
    role_colors.update({"spine": "1f77b4", "leaf": "2ca02c"})

    role_names = {node["role"] for node in toponodes}
    info(f"Ensuring device roles for {len(role_names)} unique roles...")
    roles: Dict[str, Any] = {}
    for role_name in role_names:
        roles[role_name] = ensure_device_role(nb, role_name, role_colors[role_name])

    # Ensure platforms exist for combinations of platform/version to preserve version metadata.
    unique_platform_names = {node["platform"] for node in toponodes}
    info(
        f"Ensuring platforms for {len(unique_platform_names)} unique platform values..."
    )
    platforms: Dict[str, Any] = {}
    for node in toponodes:
        platform_name = node["platform"]
        if platform_name not in platforms:
            platforms[platform_name] = ensure_platform(
                nb,
                platform_name,
                manufacturer_id=manufacturer.id,
            )

    # Map to devices.
    info(f"Ensuring {total_toponodes} devices...")
    devices: Dict[str, Any] = {}
    for index, node in enumerate(toponodes, 1):
        info(
            f"[Device {index}/{total_toponodes}] Ensuring {node['name']} ({node['role']})."
        )
        device_type = resolve_device_type(node["platform"])
        if not device_type:
            print(
                f"Device type '{node['platform']}' not found for node '{node['name']}'",
                file=sys.stderr,
            )
            continue
        platform_obj = platforms[node["platform"]]
        custom_fields_payload: Dict[str, Any] = {}
        operating_system = node.get("operating_system") or "srl"
        if operating_system:
            custom_fields_payload["operatingSystem"] = operating_system
        version_value = node.get("version")
        if version_value:
            custom_fields_payload["version"] = version_value
        on_boarded = node.get("on_boarded")
        if on_boarded is not None:
            custom_fields_payload["onBoarded"] = bool(on_boarded)
        node_profile_ref = node.get("node_profile")
        if node_profile_ref:
            custom_fields_payload["nodeProfile"] = node_profile_ref

        device = ensure_device(
            nb,
            name=node["name"],
            device_type_id=device_type.id,
            role_id=roles[node["role"]].id,
            site_id=site.id,
            platform_id=platform_obj.id,
            tag_ids=[tag.id],
            custom_fields=custom_fields_payload,
        )
        devices[node["name"]] = device

        # Ensure management interface/IP.
        mgmt_iface = ensure_interface(
            nb,
            device_id=device.id,
            name="mgmt0",
            type_slug="virtual",
            description="Management",
        )
        ensure_primary_ip(
            nb, device=device, interface=mgmt_iface, address=node["production_ipv4"]
        )

    # Create data-plane interfaces based on topology definitions.
    interface_cache: Dict[str, Dict[str, Any]] = defaultdict(dict)
    total_interface_groups = len(interface_groups)
    if total_interface_groups:
        info(
            f"Ensuring interfaces for {total_interface_groups} topology interface definitions..."
        )
    else:
        info(
            "No topology interface definitions found; skipping interface provisioning."
        )
    for idx, iface_def in enumerate(interface_groups, 1):
        group_label = (
            iface_def.get("name")
            or iface_def.get("description")
            or f"interface-group-{idx}"
        )
        info(
            f"[Interface group {idx}/{total_interface_groups}] Processing {group_label}..."
        )
        description = iface_def.get("description")
        for member in iface_def.get("members", []):
            node_name = member["node"]
            iface_name = member["interface"]
            device = devices.get(node_name)
            if not device:
                print(
                    f"Skipping interface '{iface_name}' on '{node_name}' because device is missing",
                    file=sys.stderr,
                )
                continue
            iface = ensure_interface(
                nb,
                device_id=device.id,
                name=iface_name,
                type_slug="100gbase-x-qsfp28",
                description=description,
                tag_id=tag.id,
            )
            interface_cache[node_name][iface_name] = iface

    interface_vlan_updates = 0
    edge_service_interface_ids: Set[int] = set()

    total_edge_services = len(service_edge_interfaces)
    if total_edge_services:
        info(f"Processing {total_edge_services} edge service definitions...")
    else:
        info("No edge service definitions provided; skipping edge service processing.")
    for edge_index, edge_def in enumerate(service_edge_interfaces, 1):
        edge_name = edge_def.get("name") or f"edge-{edge_index}"
        info(
            f"[Edge service {edge_index}/{total_edge_services}] Processing {edge_name}..."
        )
        edge_labels = edge_def.get("labels", {})
        vlan_targets: List[Any] = []
        edge_label_tag_ids: Set[int] = set()
        for label_key, label_value in edge_labels.items():
            if isinstance(label_value, bool):
                label_enabled = label_value
            else:
                label_enabled = str(label_value).lower() in {"true", "yes", "on", "1"}
            if not label_enabled:
                continue
            vlan_obj = ensure_vlan_from_label(label_key)
            if vlan_obj:
                vlan_targets.append(vlan_obj)
            label_tag = label_tag_cache.get(label_key)
            if label_tag is None:
                label_tag = ensure_tag(nb, label_key)
                label_tag_cache[label_key] = label_tag
            label_tag_id = getattr(label_tag, "id", None)
            if label_tag_id is not None:
                edge_label_tag_ids.add(label_tag_id)

        spec = edge_def.get("spec") or {}
        service_type = str(spec.get("type") or "").lower()
        bundle_id = None
        if service_type == "lag":
            bundle_id = edge_def.get("name") or "edge-bundle"

        for member in spec.get("members", []):
            node_name = member.get("node")
            iface_name = member.get("interface")
            if not node_name or not iface_name:
                continue
            device = devices.get(node_name)
            if not device:
                continue
            iface_obj = interface_cache.get(node_name, {}).get(iface_name)
            if not iface_obj:
                iface_obj = ensure_interface(
                    nb,
                    device_id=device.id,
                    name=iface_name,
                    type_slug="10gbase-x-sfpp",
                    description=edge_def.get("name"),
                    tag_id=edge_tag.id,
                )
                interface_cache.setdefault(node_name, {})[iface_name] = iface_obj
            if not iface_obj:
                continue

            desired_tag_ids = sorted({tag.id, edge_tag.id}.union(edge_label_tag_ids))
            update_payload: Dict[str, Any] = {"tags": desired_tag_ids}

            if vlan_targets:
                current_tagged_ids = {
                    vlan.id for vlan in getattr(iface_obj, "tagged_vlans", [])
                }
                desired_tagged_ids = current_tagged_ids | {
                    vlan.id for vlan in vlan_targets
                }
                current_mode = str(getattr(iface_obj, "mode", "") or "").lower()
                if desired_tagged_ids != current_tagged_ids or current_mode != "tagged":
                    interface_vlan_updates += 1
                update_payload["tagged_vlans"] = sorted(desired_tagged_ids)
                update_payload["mode"] = "tagged"

            if bundle_id:
                existing_cf = (getattr(iface_obj, "custom_fields", {}) or {}).get(
                    EDGE_LAG_CF_NAME
                )
                if existing_cf != bundle_id:
                    update_payload.setdefault("custom_fields", {})[EDGE_LAG_CF_NAME] = (
                        bundle_id
                    )

            iface_obj.update(update_payload)
            iface_obj = nb.dcim.interfaces.get(id=iface_obj.id)
            interface_cache[node_name][iface_name] = iface_obj
            edge_service_interface_ids.add(iface_obj.id)

    # Build cables for each logical link.
    total_link_groups = len(topolink_groups)
    total_topology_links = sum(len(group.get("links", [])) for group in topolink_groups)
    if total_topology_links:
        info(
            f"Creating cables for {total_topology_links} topology links across {total_link_groups} groups..."
        )
    else:
        info("No topology links defined; skipping cable creation.")
    for group_index, link_group in enumerate(topolink_groups, 1):
        group_name = link_group.get("name") or f"link-group-{group_index}"
        info(
            f"[Cable group {group_index}/{total_link_groups}] Processing {group_name}..."
        )
        for link in link_group.get("links", []):
            local = link.get("local", {})
            remote = link.get("remote", {})
            local_device = devices.get(local.get("node"))
            remote_device = devices.get(remote.get("node"))
            if not local_device or not remote_device:
                print(
                    f"Skipping link '{link_group['name']}' due to missing devices",
                    file=sys.stderr,
                )
                continue
            local_iface = interface_cache.get(local.get("node"), {}).get(
                local.get("interface")
            )
            remote_iface = interface_cache.get(remote.get("node"), {}).get(
                remote.get("interface")
            )
            if not local_iface or not remote_iface:
                print(
                    f"Skipping link '{link_group['name']}' due to missing interfaces",
                    file=sys.stderr,
                )
                continue
            cable = ensure_cable(
                nb,
                name=link_group["name"],
                a_iface=local_iface,
                b_iface=remote_iface,
                cable_type="smf",
                tag_ids=[tag.id, isl_tag.id],
            )
            print(
                "Linked",
                local.get("node"),
                local.get("interface"),
                "<->",
                remote.get("node"),
                remote.get("interface"),
                f"as {cable.label} (id={cable.id})",
            )

    info("Topology updates complete. Generating summary report...")
    summary_lines = [
        f"Devices ensured: {len(devices)}",
        f"Data-plane interfaces ensured: {sum(len(ifaces) for ifaces in interface_cache.values())}",
        f"Edge interface definitions processed: {len(service_edge_interfaces)}",
        f"Interfaces tagged for edge services: {len(edge_service_interface_ids)}",
        f"Interface VLAN assignments updated: {interface_vlan_updates}",
        f"VLANs ensured: {len(vlan_lookup)} ({', '.join(sorted(vlan_lookup.keys()))})"
        if vlan_lookup
        else "VLANs ensured: 0",
        f"VRFs ensured: {len(vrf_lookup)} ({', '.join(sorted(vrf_lookup.keys()))})"
        if vrf_lookup
        else "VRFs ensured: 0",
        f"L2VPNs ensured: {len(l2vpn_lookup)} ({', '.join(sorted(l2vpn_lookup.keys()))})"
        if l2vpn_lookup
        else "L2VPNs ensured: 0",
        f"IRB gateway IPs ensured: {irb_ip_addresses_ensured}",
    ]

    print("\nNetBox update summary:")
    for line in summary_lines:
        print(f"  - {line}")

    if not l2vpn_supported and service_virtual_networks:
        print(
            "  - L2VPN endpoint unavailable in NetBox; skipped creation of L2VPN objects"
        )

    print("\nTopology push to NetBox completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
