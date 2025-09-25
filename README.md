# UV-Based Ansible Demo: Create EDA TopoNodes

This demo provisions a pair of NodeProfiles (spine/leaf) and five Nokia EDA TopoNodes (2 spines, 3 leaves) inside the `eda` namespace. NodeProfiles are created/upserted first and the TopoNodes are applied via a single Core transaction. Everything is self-contained, relies on the published Nokia EDA collections, and uses [uv](https://github.com/astral-sh/uv) to manage Python dependencies.

## Layout

```
ansible-eda-demo/
├── ansible.cfg
├── inventory.yaml
├── playbooks/
│   └── create-toponodes.yaml
├── pyproject.toml
├── requirements.yml
└── vars/
    ├── nodeprofiles.yml
    └── toponodes.yml
```

- `pyproject.toml` pins the Python packages needed by the Nokia EDA collections.
- `requirements.yml` pulls in the `nokia.eda_utils_v1`, `nokia.eda_core_v1`, and `nokia.eda_apps_core_v1` collections.
- `inventory.yaml` stores connection/authentication variables (EDA credentials plus the Keycloak realms/client configuration used by the token helper). Verify the defaults for credentials, API URL, or TLS behaviour before running the demo.
- `vars/nodeprofiles.yml` defines the NodeProfiles that will be ensured present (adjust the YANG bundle URL, onboarding credentials, or OS version to match your setup).
- `vars/toponodes.yml` lists the five TopoNodes created by the demo; adjust platforms, versions, or IPs if desired.
- `playbooks/create-toponodes.yaml` acquires an access token, upserts the NodeProfiles, builds the TopoNode CR payloads (using `state=cronly`), and submits them in one transaction before waiting for the execution result.

## Prerequisites

1. [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed on your workstation.
2. Reachability to the EDA API (default URL in `inventory.yaml` is `https://100.82.85.163:9443`).
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

# 3. Review vars/nodeprofiles.yml, vars/toponodes.yml, and inventory.yaml to ensure the data matches your environment
$EDITOR inventory.yaml vars/nodeprofiles.yml vars/toponodes.yml

# 4. Execute the demo playbook
uv run ansible-playbook playbooks/create-toponodes.yaml
```

The playbook prints the transaction identifier and waits for completion (`failOnErrors: true`). If the transaction succeeds, you will see a summary of the applied changes.

## Customisation

- Toggle `tls_skip_verify` in `inventory.yaml` if your EDA endpoint presents a trusted certificate.
- Edit `vars/nodeprofiles.yml` to change credential defaults, OS versions, or the YANG bundle URL.
- Edit `vars/toponodes.yml` to change the names, roles, platforms, software versions, or production IP addresses.
- Update the Keycloak settings in `inventory.yaml` (`keycloak_*` variables) if your realm, URL path, or admin credentials differ from the defaults.
- Switch the transaction to a dry run by temporarily setting `dryRun: true` inside `playbooks/create-toponodes.yaml`.

## Cleanup

To roll back the created TopoNodes, rerun the playbook after removing or commenting the relevant entries in `vars/toponodes.yml`, or submit a new transaction with `state: absent` changes by adapting the playbook.
