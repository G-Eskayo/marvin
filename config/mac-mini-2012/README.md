# mac-mini-2012: rebuild runbook

MARVIN's third node: a 2012 Mac Mini (Macmini6,2, i7-3615QM, 16 GB, 224 GB SSD) running Kali Linux. Design: ADR 0069
and `CONTEXT.md` "Third node". Every file the box needs outside the repos is in this folder.

## 1. Install (at the box)
- Kali installer USB. Hold **Alt/Option** at power-on → EFI Boot → Graphical install.
- Hostname `mac-mini-2012`, user `marvin`. Ethernet (the Broadcom Wi-Fi needs non-free firmware: answer **No**).
- Guided, entire disk, all files in one partition. **Change `/` from ext4 to btrfs** before writing.
- Default software (Xfce + default tools: Burp Suite and Wireshark included).
- After first boot: `sudo systemctl enable --now ssh`, install Tailscale, `sudo tailscale up --hostname=mac-mini-2012`.

## 2. Access (from a Mac)
- `ssh-copy-id marvin@<tailscale ip>`; add `Host mac-mini-2012 / User marvin` to `~/.ssh/config` on **both** Macs.
- Sudo (setup phase): `/etc/sudoers.d/90-marvin-setup`, to be narrowed (ADR 0069).
- Read-only access: a GitHub **read-only deploy key** (`~/.ssh/marvin_agents_ro`, alias `github-agents-ro`) and a
  key on the M4 Mini locked by `~/.ssh/marvin-claude-pull-only.sh` to fetching `~/.claude-sync.git` (alias
  `mini-claude-ro`). Neither can push.

## 3. Box software
- `apt install btrfs-progs snapper grub-btrfs inotify-tools qemu-system-x86 libvirt-daemon-system virtinst virt-manager
  libguestfs-tools cloud-image-utils nodejs npm jq`; GitHub CLI from cli.github.com's apt repo.
- Snapshots: snapper on the flat `@.snapshots` subvolume, timeline off, NUMBER_LIMIT=10; `grub-btrfs.path`.
- VM disks on subvolume `@var@lib@libvirt@images` (nodatacow).
- Claude Code native installer; sign in once with the subscription (`~/.claude/.credentials.json`).
- `uv`, then `uv venv --python 3.11 ~/.agents/venv` and the Macs' `pip freeze` minus `mlx*` (Apple-only).
- `marvin-do` (this folder) → `~/.local/bin/`: mirrors steps into the on-screen activity window.

## 4. Repos (pull-only)
- `git clone github-agents-ro:G-Eskayo/marvin.git ~/.agents`
- `~/.claude`: `git init`, remote `mini-claude-ro:/Users/gileskayo/.claude-sync.git`, `checkout -f -B main origin/main`
  (keeps the untracked `.credentials.json`).
- `marvin-mirror.service` + `.timer` → `~/.config/systemd/user/`; `sudo loginctl enable-linger marvin`;
  `systemctl --user enable --now marvin-mirror.timer`.

## 5. Whonix
- Whonix-LXQt libvirt image, signature checked against key `916B 8D99 C38E AF5E 8ADC 7A2A 8D66 066A 2EEA CCDA`.
- Its XML uses `<disk type="volume">`, which Kali's AppArmor helper can't resolve (silent denial): redefine both VMs
  with `<disk type="file">` pointing at `/var/lib/libvirt/images/Whonix-*.qcow2`.

## 6. Disposable VMs (`lib/vm_run.py`)
- Keys: `ssh-keygen -t ed25519 -f ~/.ssh/marvin_vm` and `-f ~/.ssh/marvin_quarantine` (separate on purpose).
- `sudo bash build-golden.sh marvin-test` and `sudo bash build-golden.sh quarantine`.
- `sudo install -d -o marvin -g libvirt-qemu -m 2775 /var/lib/libvirt/images/runs`
- libvirt `default` network (autostart) for marvin-test; `virsh net-define marvin-isolated.xml` (no `<forward>`) for
  quarantine, plus `quarantine.nft` loaded by `marvin-quarantine-fw.service` (DHCP/DNS only to the host).
- VMs need a video device: with `--graphics none` Debian's GRUB reset-loops under this libvirt.

## 7. Register (only after work tags are on main)
Add to `~/.claude/marvin-network.json` on a Mac:
`"mac-mini-2012": {"tailscale_hostname": "mac-mini-2012", "os": "linux", "kind": "desktop", "accepts": ["security",
"quarantine", "test", "bench"], "hardware_uuid": "<from machine_profile on the box>"}` and give the Macs'
entries `"accepts": ["general", "macos"]`.
