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

if [[ ${#} -lt 1 ]]; then
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
    -o jsonpath="{.items[0].metadata.name}"
}

ensure_tools

case "${CMD}" in
  remove)
    echo "Removing topology from namespace ${TOPO_NS}" \
      && kubectl apply -n "${TOPO_NS}" -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: eda-topology
data:
  eda.yaml: |
    {}
