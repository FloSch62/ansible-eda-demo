# UV-Based Ansible Demo: Create EDA TopoNodes

This demo provisions a pair of NodeProfiles (spine/leaf), five Nokia EDA TopoNodes (2 spines, 3 leaves), the interfaces used to wire the fabric, and the logical TopoLinks between them inside the `eda` namespace. NodeProfiles are created/upserted first and the TopoNodes, Interfaces, and TopoLinks are applied via a single Core transaction. Everything is self-contained, relies on the published Nokia EDA collections, and uses [uv](https://github.com/astral-sh/uv) to manage Python dependencies.

## Layout

```
ansible-eda-demo/
├── ansible.cfg
├── inventories/
│   └── demo/
│       └── inventory.yaml
├── playbooks/
│   ├── deploy-environment.yaml
│   └── tasks/
│       ├── authenticate.yml
│       ├── interfaces.yml
│       ├── nodeprofiles.yml
│       ├── topolinks.yml
│       ├── toponodes.yml
│       └── transaction.yml
├── pyproject.toml
├── requirements.yml
└── vars/
    ├── fabrics/
    ├── services/
    └── topology/
        ├── nodeprofiles.yml
        ├── toponodes.yml
        └── topolinks.yml
```

- `pyproject.toml` pins the Python packages needed by the Nokia EDA collections.
- `requirements.yml` pulls in the `nokia.eda_utils_v1`, `nokia.eda_core_v1`, `nokia.eda_apps_core_v1`, and `nokia.eda_interfaces_v1alpha1` collections.
- `inventories/demo/inventory.yaml` stores connection/authentication variables (EDA credentials plus the Keycloak realms/client configuration used by the token helper). Verify the defaults for credentials, API URL, or TLS behaviour before running the demo.
- `vars/topology/nodeprofiles.yml` defines the NodeProfiles that will be ensured present (adjust the YANG bundle URL, onboarding credentials, or OS version to match your setup).
- `vars/topology/toponodes.yml` lists the five TopoNodes created by the demo; adjust platforms, versions, or IPs if desired.
- `vars/topology/topolinks.yml` describes the interface resources and TopoLinks that interconnect the nodes. Tune interface names, speeds, or link memberships to reflect your lab.
- `playbooks/deploy-environment.yaml` orchestrates the environment workflow by including the modular task files in `playbooks/tasks/`.
- `playbooks/tasks/` contains the discrete task groups for authentication, resource preparation, and transaction submission.

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

# 3. Review vars/topology/nodeprofiles.yml, vars/topology/toponodes.yml, vars/topology/topolinks.yml, and inventories/demo/inventory.yaml to ensure the data matches your environment
$EDITOR inventories/demo/inventory.yaml vars/topology/nodeprofiles.yml vars/topology/toponodes.yml vars/topology/topolinks.yml

# 4. Execute the demo playbook
uv run ansible-playbook playbooks/deploy-environment.yaml
```

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
- Edit `vars/topology/nodeprofiles.yml` to change credential defaults, OS versions, or the YANG bundle URL.
- Edit `vars/topology/toponodes.yml` to change the names, roles, platforms, software versions, or production IP addresses.
- Edit `vars/topology/topolinks.yml` to update link speeds, interface mappings, or adjacency types.
- Update the Keycloak settings in `inventories/demo/inventory.yaml` (`keycloak_*` variables) if your realm, URL path, or admin credentials differ from the defaults.
- Switch the transaction to a dry run by temporarily setting `dryRun: true` inside `playbooks/deploy-environment.yaml`.

## Cleanup

To roll back the created TopoNodes, rerun the playbook after removing or commenting the relevant entries in `vars/topology/toponodes.yml`, or submit a new transaction with `state: absent` changes by adapting the playbook.
