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
- Sudo: setup used a temporary `NOPASSWD: ALL` rule, since removed. Unattended root is now only `/etc/sudoers.d/90-marvin`: two exact `cat`s of the root-only DMI files `product_uuid` and `product_serial`. No wildcards: `snapper create *` would allow `--command`, and nothing under `~/.agents` (fed from GitHub) may run as root. Anything else takes Gil's password. Caveat: the `libvirt` group (needed by vm_run) is near-root; per-user (session) libvirt would remove that.
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
- The test harness, declared in `~/.agents/requirements-test.txt` (the venv has no pip):
  `uv pip install --python ~/.agents/venv/bin/python -r ~/.agents/requirements-test.txt`. Re-run it when that file changes.
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

## 8. Dashboard and live wallpaper
- `cd ~/.agents/dashboard && npm ci` (npm 12 runs only the install scripts named in `package.json`'s `allowScripts`:
  Electron and esbuild). Electron needs no extra system packages on Kali.
- Autostart at login: copy `marvin-dashboard.desktop` and `marvin-desktoplive.desktop` to `~/.config/autostart/`.
  `marvin-dashboard.sh` rebuilds before opening; `marvin-desktoplive.sh` runs `brain-map/desktop-live-linux/main.js`.
- The wallpaper is the Linux twin of `brain-map/DesktopLive` (same page, same hooks and timers). It must NOT use
  Electron's `type: 'desktop'`: on X11 that makes an unmanaged window drawn over everything. It sets
  `_NET_WM_WINDOW_TYPE_DESKTOP` with `xprop` before the window maps, so Xfwm keeps it behind every window.

## 9. Mac data on the box (observer key)
- The box reads from the Macs only through `marvin-observer.sh`, a forced command that matches the request against a
  fixed list and runs its own copy of the command (never the requested text). Keep it in step with the callers:
  `lib/tests/test_observer_allowlist.py` fails if a caller sends something not on the list.
- On each Mac: `restrict,command="$HOME/.agents/config/mac-mini-2012/marvin-observer.sh" <box's marvin_observer.pub>`
  in `~/.ssh/authorized_keys`. On the box, `~/.ssh/config` maps each Mac's Tailscale name to `User gileskayo`,
  `IdentityFile ~/.ssh/marvin_observer`, `IdentitiesOnly yes`.
- Health: `marvin-observer-feed.timer` copies the M4 Mini's `health-status.json` every 2 minutes (it covers all three
  machines) for the dashboard. The box's own health sweep (section 10) writes `health-status.local.json` beside it.
- GitHub on the box: a fine-grained **read-only** token (Issues, Pull requests, Checks, Commit statuses, Metadata) in
  `gh auth`. The bot's write token never lives on the box.

## 10. Scheduled jobs (marvin#911)
- One definition per job in `config/jobs/<name>.json`; `lib/job_units.py` renders it as a launchd plist on the Macs
  and as `marvin-<name>.service` + `.timer` (systemd user units) here, with the same command, schedule and logs.
  Never hand-edit the units in `~/.config/systemd/user/`: change the definition and reinstall.
- Install: `~/.agents/venv/bin/python ~/.agents/lib/job_units.py install health-check cleanup-sweep usage-scan`
  (needs linger, section 4). Re-running is a no-op when nothing changed. Check: `systemctl --user list-timers`,
  `journalctl --user -u marvin-<name>.service`, and `~/.claude/logs/<name>.log` / `<name>-error.log`.
- What they do here: the health sweep writes `health-status.local.json`; usage-scan writes `token-usage.json`; the
  cleanup sweep runs only its local, lossless steps. This is a pull-only node (`machine_profile.pull_only()`: its
  registry entry doesn't accept `general` work), so the sweep never releases claims, pushes backups or rewrites
  `~/.claude/suggestions.md`, and its log says so. With no GitHub token, anything it would need GitHub for is kept.
