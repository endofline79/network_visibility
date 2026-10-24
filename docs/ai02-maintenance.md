# AI-02 NIC installation maintenance

Prepared from live inspection on 2026-10-04. The user subsequently authorized
package installation and poweroff for NIC installation. See the execution
record below for progress; the original inventory is the pre-maintenance state.

## Execution record

- Private recovery directory on AI-02:
  `/var/backups/ai02-maintenance-20261004T223117Z` (root-only access).
- Saved package inventory, container definitions, VM definition, and host
  configuration. Sensitive configuration remains on AI-02 outside Git.
- `unifi-os` shut down gracefully; all seven running containers stopped with
  exit code 0 and no reported OOM kill.
- Copied offline Visibility data, PostgreSQL data, and the UniFi VM disk,
  attached ISO, and NVRAM to the recovery directory (7.6 GiB total).
  These are local recovery copies, not an off-host disaster recovery backup.
- Installation started as `ai02-maintenance-upgrade.service`, independently
  of SSH. Its private `upgrade.log` and `upgrade-result.json` are in the
  recovery directory. Configuration-preserving noninteractive options and
  `--no-remove` were used. No autoremove, container image updates, or firmware
  flashing was requested.
- Upgrade completed with exit code 0 at 2026-10-04 18:38 EDT. `dpkg --audit`
  was empty and `apt-get check` passed. The follow-up simulation reports no
  further upgrades except phased `dnsmasq-base`.
- AMD DKMS modules installed successfully for `7.0.0-38-generic` and
  `6.8.0-146-generic`; the new kernel and initramfs are present. Runtime GPU
  validation must occur after power-on.
- Discovered `llama-swap.service` manages the inference container and is
  enabled at boot. It restarted the container during the Docker update.
  Stopped the router cleanly before final shutdown. Its managed container uses
  Docker AutoRemove and disappeared on exit as configured; model files are
  bind-mounted and remain intact. The router recreates it on demand.
- Final checks confirmed no running containers or VMs. `systemctl poweroff`
  was issued and returned exit code 0. Confirm chassis power-off locally before
  disconnecting AC and installing the NIC; remote connection loss alone does
  not establish the physical power state.

## Post-boot observations

- AI-02 returned on kernel `7.0.0-38-generic`; no failed system services were
  reported. The UniFi VM and llama-swap started automatically.
- Restored the six persistent containers, waiting for VictoriaLogs and
  PostgreSQL readiness before starting dependent applications.
- LiteLLM liveness/readiness and the direct llama health endpoint returned
  HTTP 200. A local inference request returned HTTP 200 and a completion.
  Both AMD GPUs use `amdgpu` and each holds approximately 19.6 GB of model data.
- New NIC: Realtek RTL8125 2.5GbE, `enp132s0`, PCI `0000:84:00.0`,
  MAC `14:5d:34:c0:fa:4b`, driver `r8169`. Administratively down and unconfigured;
  no capture networking or switch mirroring has been applied.
- BMC at `192.168.5.132`, MAC `9c:6b:00:cb:38:34`, answered ping and HTTP(S).
- During physical cabling changes, kernel logs recorded `eno1` losing and
  regaining link, then `eno2` losing link. After cable correction, the check
  around 19:01 EDT confirmed both Intel links up at 1 Gbps, both VLAN interfaces
  and bridges up, and the UniFi VM reachable. The telemetry and flow collectors
  and PostgreSQL reported healthy; all seven intended containers were running.
  Fresh firewall logs and UniFi/Pi-hole snapshots were present.
- IPMI HTTPS still responded after this correction. The new `enp132s0`
  remained administratively down; its physical cable status is not established
  by that state. No switch mirror or capture interface configuration was applied.

## Pre-maintenance state

- SSH: `ssh -F /home/klab/.ssh/config klab@192.168.5.230`
- Running kernel: `7.0.0-30-generic`; a reboot is already required.
- Refreshed `apt-get -s dist-upgrade`: 80 upgrades, 33 new packages,
  zero removals; `dnsmasq-base` deferred by phasing.
- Updates include kernel `7.0.0-38-generic`, Docker/containerd, QEMU,
  Mesa, Linux firmware, and Netplan packages. No release upgrade proposed.
- `dpkg --audit` and `apt-mark showhold` returned no entries.
- Root has 162 GiB free; `/boot` has 1.3 GiB free.
- AMD GPU uses an out-of-tree DKMS module. Installed builds exist for
  `7.0.0-30-generic`, `7.0.0-34-generic`, and `6.8.0-142-generic`.
- `unifi-os` is the only running VM and has autostart enabled;
  `ai-browser` is shut off. `libvirt-guests` is enabled and configured
  for guest shutdown with a 120-second timeout.
- Six active containers use `unless-stopped`: the four Visibility services,
  `litellm`, and `litellm-postgres`.
- `dual-amd-qwen38-27b-ud-q8-k-xl-llama` was running with Docker restart policy
  `no`, but is managed by the boot-enabled `llama-swap.service` (discovered
  during execution). Keep the existing stopped dashboard and browser VM stopped.
- Local IPMI sensor access works through `/dev/ipmi0`, independently of the
  dedicated BMC Ethernet cable.

## Execution gate

Confirm the maintenance window before updates or poweroff. Docker and other
package upgrades may restart services before the eventual shutdown. Host
telemetry, the UniFi controller, and inference will be unavailable during the
window; UDP telemetry arriving while the collector is stopped can be lost.

Before executing, save host configuration and package-version inventory to a
private maintenance directory outside Git, including Netplan, VM definitions,
and relevant service configuration. Do not print or commit credentials.
Verify appropriate database/VM backups exist before package changes; this
preparation did not create or verify backups.

## Update and shutdown sequence

Run host commands on AI-02. Recheck active workloads and package operations.
Gracefully shut down the controller VM before QEMU updates:

```bash
virsh -c qemu:///system shutdown unifi-os
virsh -c qemu:///system domstate unifi-os
```

Wait until the state is `shut off`. If it does not stop, investigate; do not
use `virsh destroy` or force host shutdown.

After update authorization, repeat the simulation, then install while
preserving existing configuration unless a specific change is reviewed:

```bash
sudo apt-get -s dist-upgrade
sudo apt-get --no-remove dist-upgrade
sudo dpkg --audit
dkms status
modinfo -k 7.0.0-38-generic -F filename amdgpu
```

Do not force phased updates, run autoremove, pull container images, or flash
BIOS/BMC firmware as part of this procedure. The kernel version above is the
observed candidate; adjust checks if the reviewed candidate changes.
Require successful package configuration and a successful AMD DKMS build for
the new kernel before continuing. A dry-run cannot establish driver build
compatibility. Retain existing kernels for recovery.

At the final shutdown stage, stop producers before their databases. Use
`docker stop --timeout -1` in the following order, waiting and inspecting each
result; this waits for graceful exit instead of imposing a forced-kill deadline:

1. `visibility-telemetry-1`, `visibility-flows-1`, and `visibility-api-1`.
2. `visibility-logs-1` after the producers have exited.
3. `litellm`, then `sudo systemctl stop llama-swap.service`. Verify its managed
   inference container exits; AutoRemove means it may no longer exist afterward.
4. `litellm-postgres` after its client has exited.

If a service hangs, investigate before continuing. Record the names of all
manually stopped containers: `unless-stopped` containers explicitly stopped
this way need an explicit start after boot. Check that no unexpected running
containers or VMs remain, then:

```bash
sync
sudo systemctl poweroff
```

Verify the chassis is powered off locally; loss of SSH alone is not proof.
Disconnect AC power before installing the PCIe NIC, following the chassis
procedure. Disconnecting only the BMC Ethernet cable does not remove standby
power. Do not change switch mirroring or host networking during this step.

## Return to service

After physical power-on, verify SSH and existing interfaces before configuring
the new NIC:

```bash
uname -r
ip -br link
ip -br address
ip route
virsh -c qemu:///system list --all
sudo ipmitool -I open sensor list
dkms status
```

Expect `unifi-os` to autostart; investigate if it does not. Explicitly restore
the persistent containers in dependency order: VictoriaLogs and PostgreSQL first,
then verify the llama-swap service, followed by LiteLLM and the Visibility API/collectors.
Use `docker start NAME` on existing containers; do not recreate or pull images.
Wait for database readiness before starting dependents.

For this recorded maintenance, the exact existing-container start sequence is:

```bash
docker start visibility-logs-1 litellm-postgres
# Wait for VictoriaLogs readiness and PostgreSQL health before continuing.
systemctl is-active llama-swap.service
# It is boot-enabled; if inactive, investigate and start the service as needed.
# The router recreates its disposable model container on demand.
docker start litellm
docker start visibility-api-1 visibility-telemetry-1 visibility-flows-1
docker ps --format '{{.Names}}\t{{.Status}}'
```

Verify container health, fresh telemetry ingestion, UniFi access, and an actual
inference request. Confirm both GPUs are available to the inference runtime.
Identify the new NIC by PCI address and MAC before configuring capture. Its
appearance may affect interface naming, so verify the existing management link
and VLAN bridges against the saved configuration.

## Recovery

If the new kernel prevents normal operation, use the local console and GRUB's
advanced options to boot the previously working `7.0.0-30-generic` kernel.
This does not roll back userspace packages; package recovery is a separate,
reviewed operation using the saved inventory and backups. If hardware addition
causes boot problems, power off and disconnect AC before removing the new NIC.
Restore any changed cabling and switch configuration if reverting the capture
setup. Do not delete volumes, VM disks, or telemetry data.
