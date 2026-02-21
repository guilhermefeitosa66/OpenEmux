#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found. Install Docker to run AppImage build."
  exit 1
fi

ARCH="$(uname -m)"
if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "amd64" ]; then
  echo "Unsupported build architecture: $ARCH (expected amd64/x86_64)."
  exit 1
fi

"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/build_in_docker.sh"
