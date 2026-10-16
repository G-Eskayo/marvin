#!/bin/bash
# Build a golden VM image for vm_run.py on mac-mini-2012 (ADR 0069). Run as root on the box.
#   sudo bash build-golden.sh marvin-test   # clean MARVIN test env: uv + Python 3.11, sudo inside, key marvin_vm
#   sudo bash build-golden.sh quarantine    # untrusted code: no MARVIN, no sudo, key marvin_quarantine
# Base: Debian 13 genericcloud, checksum-verified. The result is read-only; runs only ever use copies of it.
set -euo pipefail
image=${1:?usage: build-golden.sh marvin-test|quarantine}
home=/home/marvin
cd /var/lib/libvirt/images/golden
base=debian-13-genericcloud-amd64.qcow2
if [ ! -f "$base" ]; then
  curl -fsSL -o SHA512SUMS https://cloud.debian.org/images/cloud/trixie/latest/SHA512SUMS
  curl -fsSL -o "$base" "https://cloud.debian.org/images/cloud/trixie/latest/$base"
fi
grep " $base\$" SHA512SUMS | sha512sum -c -

common=(--run-command "growpart /dev/sda 1 || true; resize2fs /dev/sda1 || true"
        --write "/etc/cloud/cloud.cfg.d/99-marvin.cfg:datasource_list: [ NoCloud, None ]")
case "$image" in
  marvin-test)
    extra=(--install git,curl,ca-certificates,rsync,jq,nodejs,npm,build-essential
           --run-command 'useradd -m -s /bin/bash marvin && echo "marvin ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/marvin'
           --ssh-inject "marvin:file:$home/.ssh/marvin_vm.pub"
           --run-command 'su - marvin -c "curl -LsSf https://astral.sh/uv/install.sh | sh && ~/.local/bin/uv python install 3.11"') ;;
  quarantine)
    extra=(--install git,curl,ca-certificates,python3,python3-venv,python3-pip,nodejs,npm,build-essential,jq,strace,tcpdump
           --run-command 'useradd -m -s /bin/bash marvin'
           --ssh-inject "marvin:file:$home/.ssh/marvin_quarantine.pub") ;;
  *) echo "unknown image $image" >&2; exit 1 ;;
esac

cp --sparse=always "$base" "$image.building.qcow2"
qemu-img resize -q "$image.building.qcow2" 20G
virt-customize -q -a "$image.building.qcow2" --hostname "$image" "${common[@]}" "${extra[@]}" \
  --run-command "truncate -s0 /etc/machine-id" --run-command "apt-get clean"
[ -f "$image.qcow2" ] && chmod 644 "$image.qcow2"
mv "$image.building.qcow2" "$image.qcow2"
chmod 444 "$image.qcow2"
qemu-img info "$image.qcow2" | grep -E "virtual size|disk size"
