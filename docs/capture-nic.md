# AI-02 dedicated capture NIC

This records the NIC preparation verified on 2026-10-04, when switch mirroring
and the capture VM were not configured. It is a historical snapshot, not the
current switch configuration. Later presentation source records an October 5
mirror from source port 1 to destination port 4; the October 12
[layout release](layout-release-2026-10-12.md) records incomplete capture
intervals. Reinspect the current wiring and configuration before using the
remaining-work or rollback instructions below.

## Hardware and connection

| Item | Verified value |
| --- | --- |
| Host | AI-02, management `192.168.5.230` on `eno1` |
| Capture interface | `enp132s0` |
| MAC | `14:5d:34:c0:fa:4b` |
| PCI device | `0000:84:00.0`, Realtek RTL8125 2.5GbE |
| Driver | `r8169`, kernel `7.0.0-38-generic` |
| Negotiated link | 2500 Mb/s, full duplex |
| LLDP neighbor | USW-Flex-2.5G-8-PoE, port 7 |

The NIC has no IPv4/IPv6 addresses, DHCP, router-advertisement acceptance,
link-local addressing, gateway, or bridge membership. It is matched by MAC so
the configuration remains applicable if its Linux interface name changes.
It is marked optional so it is excluded from Netplan's boot wait requirements.

## Persistent configuration

AI-02 file: `/etc/netplan/60-capture.yaml` (root-owned, mode 0600).

```yaml
network:
  version: 2
  ethernets:
    capture-nic:
      match:
        macaddress: "14:5d:34:c0:fa:4b"
      renderer: networkd
      dhcp4: false
      dhcp6: false
      accept-ra: false
      link-local: []
      optional: true
```

The existing `/etc/netplan/50-cloud-init.yaml` was preserved. Source and generated
configuration hashes for existing networks were checked before application.
The new configuration was first validated with `netplan generate --root-dir`
in `/var/tmp/ai02-capture-netplan-r6trax7j`.

Application used `netplan generate`, `networkctl reload`, and
`networkctl reconfigure enp132s0`. Networkd also reapplied existing generated
configurations on reload; the host's IPv6 address temporarily disappeared and
returned. Final checks verified the original management IPv4/IPv6 addresses,
default route, `eno2` link, and UniFi connectivity.

Recovery files on AI-02:
`/var/backups/ai02-capture-20261004T230318Z` contains the prior Netplan directory,
address/route snapshots, and application record. This directory is private and
outside Git.

## Validation

Run on AI-02:

```bash
ip -br address show enp132s0
sudo ethtool enp132s0
networkctl status enp132s0 --no-pager
ip route show default
```

Expected: link UP, no addresses, 2500 Mb/s full duplex, and the default route
still through `192.168.5.1` on `eno1`. Networkd may report online state
`offline` for an intentionally unaddressed NIC; carrier and configuration state
are the relevant checks. The generated wait-online configuration excludes it.

A five-second AF_PACKET test received eight frames, including LLDP and IPv4.
The test enabled promiscuous membership only for its socket, saved no payload,
and left promiscuity at zero after closing. This verifies packet reception,
not that the switch is mirroring other ports. Services remained running, with
healthy telemetry/flow collectors and PostgreSQL. UniFi was reachable.

No reboot was needed; boot persistence follows from the installed Netplan file
but has not yet been tested through another reboot.

## Remaining capture work

Choose and configure switch mirror sources with port 7 as the intended
destination, after checking its current use. IPMI at `192.168.5.132` was still
reachable during these checks; its exact current physical path is unverified.
LLDP directly identifies the new capture NIC's switch connection.

Connect the capture VM to this feed using an explicitly chosen method such as
PCI passthrough or a configured virtual mirror path. A normal virtual bridge
does not automatically deliver all mirrored unicast frames to a guest. Keep
capture separate from management and the existing VLAN bridges. Configure
capture/offload behavior and validate coverage at that stage.

## Rollback

After reviewing the current state, these commands on AI-02 disable only the
new configuration and return the capture NIC to an unmanaged, down state:

```bash
sudo mv /etc/netplan/60-capture.yaml /etc/netplan/60-capture.yaml.disabled
sudo netplan generate
sudo networkctl reload
sudo ip link set dev enp132s0 down
```

Do not overwrite the existing Netplan file. Recheck management connectivity and
the VLAN trunk after any networkd reload. The disabled file is retained for
recovery; no backup or network data needs to be deleted.
