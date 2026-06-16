# Requirements

## Hardware

- Intel i3 mini-PC
- 16 GB RAM
- 4x Intel i226-V 2.5GbE
- SSD

## Software

- OpenMPTCProuter v0.63 x86_64 ext4 EFI (kernel 6.6+)
- `sqm-scripts`, LuCI addons from `scripts/install-luci-addons.sh`
- `adguardhome` (in OMR)

## Network

- Two ISP WANs (e.g. Fiber PPPoE + Coax DHCP)
- No external VPS required

## Routing

Per-device WAN affinity: nft MAC marking + single-nexthop tables 100/101 + post-tracking hook
`098-wan-affinity` for failover. Applied by `scripts/configure-wan-affinity.sh`.

mwan3 NOT installable on OMR (depends on `iptables-mod-conntrack-extra`, missing on
nftables-only system). Per-device affinity via kernel ip rules is used instead.

## Out of scope (v1)

- 4G/LTE backup (no wwan0 wired, no SIM modem)
- MPTCP+VPS bonding (no external VPS endpoint)
