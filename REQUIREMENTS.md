# Requirements

## Hardware

- Intel i3 mini-PC
- 16 GB RAM
- 4x Intel i226-V 2.5GbE
- SSD

## Software

- OpenMPTCProuter v0.63 x86_64 ext4 EFI (kernel 6.6+; provides `net.ipv4.fib_multipath_hash_policy`)
- `sqm-scripts`, LuCI addons from `scripts/install-luci-addons.sh`
- `adguardhome` (in OMR)
- Optional: OMR VPS only for true bonding mode

mwan3 NOT installable on OMR (depends on `iptables-mod-conntrack-extra`, missing on nftables-only system). Use kernel ECMP instead.

## Network

- Two ISP WANs (Fiber PPPoE + Coax DHCP)
- VPS not required for default load balancing
- Optional VPS latency target <20ms if bonding enabled

## Out of scope (v1)

- 4G/LTE backup (no wwan0 wired, no SIM modem)
