#!/bin/bash

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  topo.sh load <topology-yaml> <simtopology-yaml>
  topo.sh remove

Environment:
  TOPO_NS   Namespace that stores the topology ConfigMaps (default: eda)
  CORE_NS   Namespace where the eda-toolbox pod lives (default: eda-system)
USAGE
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

CMD=${1}
TOPO_FILE=${2:-}
SIM_FILE=${3:-}
TOPO_NS=${TOPO_NS:-eda}
CORE_NS=${CORE_NS:-eda-system}

ensure_tools() {
  for bin in kubectl yq; do
    if ! command -v "${bin}" >/dev/null 2>&1; then
      echo "Error: ${bin} is required but not present in PATH" >&2
      exit 1
    fi
  done
}

find_toolbox_pod() {
  kubectl -n "${CORE_NS}" get pods \
    -l eda.nokia.com/app=eda-toolbox \
    -o jsonpath='{.items[0].metadata.name}'
}

update_configmap() {
  local name=${1}
  local key=${2}
  local file=${3}

  kubectl create configmap "${name}" \
    --from-file="${key}=${file}" \
    --dry-run=client -o yaml \
    | kubectl apply -n "${TOPO_NS}" -f - >/dev/null
}

load_topology() {
  if [[ -z "${TOPO_FILE}" || -z "${SIM_FILE}" ]]; then
    echo "Error: load requires <topology-yaml> and <simtopology-yaml> arguments" >&2
    usage
    exit 1
  fi

  if [[ ! -f "${TOPO_FILE}" ]]; then
    echo "Topology file '${TOPO_FILE}' does not exist" >&2
    exit 1
  fi

  if [[ ! -f "${SIM_FILE}" ]]; then
    echo "Simulation topology file '${SIM_FILE}' does not exist" >&2
    exit 1
  fi

  local tmp_dir
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "'"${tmp_dir}"'"' EXIT

  local topo_json="${tmp_dir}/topology.json"
  local sim_json="${tmp_dir}/simtopology.json"

  yq eval -o=json '.' "${TOPO_FILE}" > "${topo_json}"
  yq eval -o=json '.' "${SIM_FILE}" > "${sim_json}"

  echo "Updating ConfigMaps in namespace ${TOPO_NS}"
  update_configmap "eda-topology" "eda.yaml" "${topo_json}"
  update_configmap "eda-topology-sim" "sim.yaml" "${sim_json}"

  local toolbox_pod
  toolbox_pod=$(find_toolbox_pod)

  if [[ -z "${toolbox_pod}" ]]; then
    echo "Could not find eda-toolbox pod in namespace ${CORE_NS}" >&2
    exit 1
  fi

  echo "Copying topology JSON into ${CORE_NS}/${toolbox_pod}"
  kubectl -n "${CORE_NS}" cp "${topo_json}" "${toolbox_pod}:/tmp/topology.json"
  kubectl -n "${CORE_NS}" cp "${sim_json}" "${toolbox_pod}:/tmp/simtopology.json"

  echo "Loading topology via api-server-topo"
  kubectl -n "${CORE_NS}" exec "${toolbox_pod}" -- api-server-topo -n "${TOPO_NS}" -f /tmp/topology.json -s /tmp/simtopology.json
}

remove_topology() {
  echo "Removing topology from namespace ${TOPO_NS}"
  kubectl apply -n "${TOPO_NS}" -f - <<'EOF' >/dev/null
apiVersion: v1
kind: ConfigMap
metadata:
  name: eda-topology
data:
  eda.yaml: |
    {}
EOF

  echo "Removing simulation topology from namespace ${TOPO_NS}"
  kubectl apply -n "${TOPO_NS}" -f - <<'EOF' >/dev/null
apiVersion: v1
kind: ConfigMap
metadata:
  name: eda-topology-sim
data:
  sim.yaml: |
    {}
EOF

  local toolbox_pod
  toolbox_pod=$(find_toolbox_pod)

  if [[ -z "${toolbox_pod}" ]]; then
    echo "Could not find eda-toolbox pod in namespace ${CORE_NS}" >&2
    exit 1
  fi

  echo "Triggering api-server-topo to reload with empty datasets"
  kubectl -n "${CORE_NS}" exec "${toolbox_pod}" -- api-server-topo -n "${TOPO_NS}"
}

ensure_tools

case "${CMD}" in
  load)
    load_topology
    ;;
  remove)
    remove_topology
    ;;
  *)
    usage
    exit 1
    ;;
 esac
