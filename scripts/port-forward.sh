#!/usr/bin/env bash
set -euo pipefail

namespace="${NAMESPACE:-shopsphere}"
local_port="${LOCAL_PORT:-8080}"

if ! command -v kubectl >/dev/null 2>&1; then
  printf 'kubectl is required but was not found in PATH.\n' >&2
  exit 127
fi

if ! kubectl get service frontend -n "$namespace" >/dev/null; then
  printf 'Service frontend was not found in namespace %s.\n' "$namespace" >&2
  exit 1
fi

printf 'ShopSphere is available at http://localhost:%s\n' "$local_port"
printf 'Press Ctrl-C to stop the port-forward.\n'

exec kubectl port-forward \
  --address 127.0.0.1 \
  --namespace "$namespace" \
  service/frontend \
  "${local_port}:80"
