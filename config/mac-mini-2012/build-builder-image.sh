#!/bin/bash
# Build the marvin-build golden image on mac-mini-2012 (marvin #950, ADR 0069), as the box's user: no sudo.
#   bash ~/.agents/config/mac-mini-2012/build-builder-image.sh
# vm_run boots a throwaway copy of golden/marvin-test, runs builder/provision.sh in it, and only if that succeeds shuts
# it down and flattens it into runs/golden/marvin-build.qcow2 (read-only). Every box ticket build runs on a throwaway
# copy of that file; nothing writes to it. A failed build leaves the previous image in place and no VM behind.
# Takes ~15-25 min on the box (downloads Node, Claude Code and the venv).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
lib="$(cd "$here/../../lib" && pwd)"
out=/var/lib/libvirt/images/runs/golden
mkdir -p "$out"
"$HOME/.agents/venv/bin/python" "$lib/vm_run.py" --image marvin-test --repo-dir "$here/builder" \
  --memory-mb 4096 --vcpus 4 --timeout 5400 --freeze-to "$out/marvin-build.qcow2" -- bash provision.sh
qemu-img info "$out/marvin-build.qcow2" | grep -E "virtual size|disk size"
