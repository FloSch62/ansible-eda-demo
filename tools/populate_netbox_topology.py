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
from typing import Any, Dict, Iterable, List

import pynetbox
import yaml
import requests

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SITE_NAME = "EDA Demo"
DEFAULT_TAG_NAME = "eda-demo-topology"


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


def ensure_platform(nb: pynetbox.api.Api, name: str, manufacturer_id: int | None = None) -> Any:
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


def ensure_config_context(nb: pynetbox.api.Api, *, name: str, data: Dict[str, Any], role_id: int) -> Any:
    context = nb.extras.config_contexts.get(name=name)
    payload = {
        "name": name,
        "data": data,
        "is_active": True,
        "weight": 100,
        "roles": [role_id],
    }
    if context:
        context.update(payload)
        return context
    return nb.extras.config_contexts.create(payload)


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

    cf = nb.extras.custom_fields.get(name=name)
    payload: Dict[str, Any] = {
        "name": name,
        "type": field_type,
        "content_types": ["dcim.device"],
        "object_types": ["dcim.device"],
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


def ensure_primary_ip(nb: pynetbox.api.Api, *, device: Any, interface: Any, address: str) -> Any:
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


def ensure_cable(
    nb: pynetbox.api.Api,
    *,
    name: str,
    a_iface: Any,
    b_iface: Any,
    cable_type: str,
    tag_id: int,
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
        "tags": [tag_id],
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

    nb = pynetbox.api(netbox_url, token=token)

    nodeprofiles = load_yaml(BASE_DIR / "vars/topology/nodeprofiles.yml")["nodeprofiles"]
    toponodes = load_yaml(BASE_DIR / "vars/topology/toponodes.yml")["toponodes"]
    topology_links = load_yaml(BASE_DIR / "vars/topology/topolinks.yml")

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

    # Pre-load manufacturer lookup.
    manufacturer = nb.dcim.manufacturers.get(name="Nokia")
    if not manufacturer:
        manufacturer = nb.dcim.manufacturers.create({"name": "Nokia", "slug": "nokia"})

    device_types = list(nb.dcim.device_types.filter(manufacturer_id=manufacturer.id))

    def resolve_device_type(model_name: str) -> Any | None:
        for candidate in device_types:
            if candidate.model.lower().startswith(model_name.lower()):
                return candidate
        return None

    site = ensure_site(nb, DEFAULT_SITE_NAME)
    tag = ensure_tag(nb, DEFAULT_TAG_NAME)

    # Clean up existing demo cables to ensure idempotency.
    for cable in nb.dcim.cables.filter(tag=tag.slug, limit=0):
        cable.delete()

    role_colors = defaultdict(lambda: "9e9e9e")
    role_colors.update({"spine": "1f77b4", "leaf": "2ca02c"})

    roles: Dict[str, Any] = {}
    for role_name in {node["role"] for node in toponodes}:
        roles[role_name] = ensure_device_role(nb, role_name, role_colors[role_name])

    # Prepare nodeprofile contexts keyed by profile name.
    profile_contexts: Dict[str, Any] = {}
    for key, profile in nodeprofiles.items():
        role = roles.get(key)
        if not role:
            print(f"Skipping profile '{key}' because device role '{key}' is missing", file=sys.stderr)
            continue
        context_name = profile["name"]
        context_payload = {
            "node_profile": {
                "name": profile["name"],
                "spec": profile.get("spec", {}),
            }
        }
        profile_contexts[profile["name"]] = ensure_config_context(
            nb,
            name=context_name,
            data=context_payload,
            role_id=role.id,
        )

    # Ensure platforms exist for combinations of platform/version to preserve version metadata.
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
    devices: Dict[str, Any] = {}
    for node in toponodes:
        device_type = resolve_device_type(node["platform"])
        if not device_type:
            print(f"Device type '{node['platform']}' not found for node '{node['name']}'", file=sys.stderr)
            continue
        platform_obj = platforms[node["platform"]]
        profile = nodeprofiles.get(node["role"], {})
        profile_spec: Dict[str, Any] = profile.get("spec", {})
        custom_fields_payload: Dict[str, Any] = {}
        operating_system = profile_spec.get("operatingSystem")
        if operating_system:
            custom_fields_payload["operatingSystem"] = operating_system
        version_value = node.get("version") or profile_spec.get("version")
        if version_value:
            custom_fields_payload["version"] = version_value
        on_boarded = profile_spec.get("onBoarded")
        if on_boarded is not None:
            custom_fields_payload["onBoarded"] = bool(on_boarded)

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
        ensure_primary_ip(nb, device=device, interface=mgmt_iface, address=node["production_ipv4"])

    # Create data-plane interfaces based on topology definitions.
    interface_cache: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for iface_def in topology_links.get("topolink_interfaces", []):
        description = iface_def.get("description")
        for member in iface_def.get("members", []):
            node_name = member["node"]
            iface_name = member["interface"]
            device = devices.get(node_name)
            if not device:
                print(f"Skipping interface '{iface_name}' on '{node_name}' because device is missing", file=sys.stderr)
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

    # Build cables for each logical link.
    for link_group in topology_links.get("topolinks", []):
        for link in link_group.get("links", []):
            local = link.get("local", {})
            remote = link.get("remote", {})
            local_device = devices.get(local.get("node"))
            remote_device = devices.get(remote.get("node"))
            if not local_device or not remote_device:
                print(f"Skipping link '{link_group['name']}' due to missing devices", file=sys.stderr)
                continue
            local_iface = interface_cache.get(local.get("node"), {}).get(local.get("interface"))
            remote_iface = interface_cache.get(remote.get("node"), {}).get(remote.get("interface"))
            if not local_iface or not remote_iface:
                print(f"Skipping link '{link_group['name']}' due to missing interfaces", file=sys.stderr)
                continue
            cable = ensure_cable(
                nb,
                name=link_group["name"],
                a_iface=local_iface,
                b_iface=remote_iface,
                cable_type="smf",
                tag_id=tag.id,
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

    print("Topology push to NetBox completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
