# UV-Based Ansible Demo: Create EDA TopoNodes

This demo provisions five Nokia EDA TopoNodes (2 spines, 3 leaves), the interfaces used to wire the fabric, and the logical TopoLinks between them inside the `eda` namespace. TopoNodes, Interfaces, and TopoLinks are applied via a single Core transaction while reusing the stock NodeProfiles that ship with EDA (for example `srlinux-ghcr-25.7.2` and `srlinux-ghcr-25.7.1`). Everything is self-contained, relies on the published Nokia EDA collections, and uses [uv](https://github.com/astral-sh/uv) to manage Python dependencies.

## Layout

```
ansible-eda-demo/
├── ansible.cfg
├── inventories/
│   └── demo/
│       └── inventory.yaml
├── playbooks/
│   ├── deploy-environment.yaml
│   ├── tasks/
│   │   ├── authenticate.yml
│   │   ├── cx_topology.yml
│   │   ├── interfaces.yml
│   │   ├── topolinks.yml
│   │   ├── toponodes.yml
│   │   └── transaction.yml
│   └── templates/
│       ├── cx_topology.yaml.j2
│       ├── interface_resource.json.j2
│       ├── netbox_topology.json.j2
│       ├── topolink_resource.json.j2
│       └── toponode_resource.json.j2
├── pyproject.toml
├── requirements.yml
├── tools/
│   └── topology/
│       └── topo.sh
└── vars/
    ├── fabrics/
    ├── services/
    └── topology/
        ├── simtopo.yml
        ├── toponodes.yml
        └── topolinks.yml
```

- `pyproject.toml` pins the Python packages needed by the Nokia EDA collections.
- `requirements.yml` pulls in the `nokia.eda_utils_v1`, `nokia.eda_core_v1`, `nokia.eda_apps_core_v1`, and `nokia.eda_interfaces_v1alpha1` collections.
- `inventories/demo/inventory.yaml` stores connection/authentication variables (EDA credentials plus the Keycloak realms/client configuration used by the token helper). Verify the defaults for credentials, API URL, or TLS behaviour before running the demo.
- `vars/topology/toponodes.yml` lists the five TopoNodes created by the demo; adjust platforms, versions, or IPs if desired.
- `vars/topology/topolinks.yml` describes the interface resources and TopoLinks that interconnect the nodes. Tune interface names, speeds, or link memberships to reflect your lab.
- `playbooks/deploy-environment.yaml` orchestrates the environment workflow by including the modular task files in `playbooks/tasks/`.
- `playbooks/tasks/` contains the discrete task groups for authentication, resource preparation, CX tooling integration, and transaction submission.
- `playbooks/templates/cx_topology.yaml.j2` renders a lab-ready topology document that mirrors the active inventory.
- `tools/topology/topo.sh` provides helper commands to push the generated topology and simulation topology into CX via the toolbox pod.
- `vars/topology/simtopo.yml` lists the simulated servers that should be attached to each leaf interface.

## Prerequisites

1. [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed on your workstation.
2. Reachability to the EDA API
3. The reference `ansible-collections` repository available as a sibling directory (the included `requirements.yml` installs the collections directly from those sources).
4. Valid EDA credentials. The playbook defaults to the platform's factory credentials (`admin` / `admin`) and will auto-discover the `client_secret` via Keycloak when it is omitted.

## Usage

```bash
cd ansible-eda-demo

# 1. Install the Python dependencies into a uv-managed virtualenv
uv sync

# 2. Install the Nokia EDA Ansible collections into the environment (expects this demo to live alongside the
#    reference ansible-collections repo so the local sources in requirements.yml resolve)
uv run ansible-galaxy collection install -r requirements.yml

# 3. Review vars/topology/toponodes.yml, vars/topology/topolinks.yml, and inventories/demo/inventory.yaml to ensure the data matches your environment
$EDITOR inventories/demo/inventory.yaml vars/topology/toponodes.yml vars/topology/topolinks.yml

# 4. Execute the demo playbook
uv run ansible-playbook playbooks/deploy-environment.yaml

#   Add -e manage_cx_topology=true to automatically load the CX topology and sim nodes via topo.sh
uv run ansible-playbook playbooks/deploy-environment.yaml -e manage_cx_topology=true
```

### Managing CX simulation topology

Enabling `manage_cx_topology=true` causes the playbook to render an aggregated CX topology, copy `vars/topology/simtopo.yml`, and invoke `tools/topology/topo.sh` so the eda-toolbox pod loads both documents. Override the target namespaces with `cx_topology_namespace` (default `eda`) and `cx_toolbox_namespace` (default `eda-system`). Set `cx_topology_state=absent` when you want the playbook to call `topo.sh remove` and clear the ConfigMaps.

The helper script can also be used directly:

```bash
tools/topology/topo.sh load /path/to/topology.yaml /path/to/simtopo.yaml
tools/topology/topo.sh remove
```

### Using NetBox as the topology source

To drive the demo from NetBox data instead of the local YAML files:

1. Populate NetBox with the demo devices, interfaces, and cables (for example with `tools/populate_netbox_topology.py`).
2. Set `topology_source: netbox` in `inventories/demo/inventory.yaml` or pass `-e topology_source=netbox` on the command line.
3. Provide NetBox connectivity details via inventory or extra vars:
   - `netbox_api_endpoint`: Base URL of the NetBox instance (e.g. `http://100.82.85.165/`).
   - `netbox_token`: API token with read access (defaults to the `NETBOX_TOKEN` environment variable).
   - `netbox_topology_tag`: Tag that identifies the demo objects (defaults to `eda-demo-topology`).
4. Run the playbook as usual. The pre-tasks will use the `netbox.netbox.nb_lookup` lookup plugin to build TopoNodes, interfaces, and links before submitting the Nokia EDA transaction.

Switch `topology_source` back to `local` to return to the repository-provided variables without touching NetBox.

The playbook prints the transaction identifier and waits for completion (`failOnErrors: true`). If the transaction succeeds, you will see a summary of the applied changes.

## Linting

The repository ships with strict linting profiles to keep the Ansible content healthy:

```bash
# Run the ansible-lint profile (fails on warnings, excludes the local collections cache)
uv run ansible-lint .

# Run the standalone yamllint pass with the hardened ruleset
uv run yamllint -s .
```

Both commands use the configuration files in the project root (`.ansible-lint` and `.yamllint`).

- ansible-lint runs with the built-in `complexity` rule enabled and caps block depth at 3 for easier-to-follow playbooks.
- yamllint is configured with a strict style guide, ignores generated caches (`.venv`, `.uv`, `collections/`), and enforces document headers, indentation, truthy usage, and octal restrictions.

## Customisation

- Toggle `tls_skip_verify` in `inventories/demo/inventory.yaml` if your EDA endpoint presents a trusted certificate.
- Edit `vars/topology/toponodes.yml` to change the names, roles, platforms, software versions, or production IP addresses.
- Edit `vars/topology/topolinks.yml` to update link speeds, interface mappings, or adjacency types.
- Update the Keycloak settings in `inventories/demo/inventory.yaml` (`keycloak_*` variables) if your realm, URL path, or admin credentials differ from the defaults.
- Switch the transaction to a dry run by temporarily setting `dryRun: true` inside `playbooks/deploy-environment.yaml`.

## Cleanup

To roll back the created TopoNodes, rerun the playbook after removing or commenting the relevant entries in `vars/topology/toponodes.yml`, or submit a new transaction with `state: absent` changes by adapting the playbook.
