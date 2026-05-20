# NexusGate

Open-source operation-aware multi-WAN SD-WAN router for Intel i3 mini-PCs running OpenMPTCProuter/OpenWrt.

Default mode uses both 1Gb WAN links by balancing **operations/flows**, not machines. One PC can use both WANs at the same time when apps open multiple connections. Gaming/VoIP stay pinned to one WAN for stable latency/no packet drops.

## Default behavior

- Normal traffic: per-flow 50/50 WAN1/WAN2, non-sticky.
- Downloads/package managers/cloud sync: spread flows across both WANs.
- One device can consume aggregate ~2Gb when workload is multi-flow.
- Gaming/VoIP/video calls: sticky best-latency WAN.
- Banking/login-sensitive domains: optional sticky WAN.
- 4G/LTE: backup only.
- SQM/CAKE: low latency under load.

## Ports / physical cabling

| Port | Role | Use |
|---|---|---|
| `eth0` | WAN1 | ISP modem/router #1 |
| `eth1` | WAN2 | ISP modem/router #2 |
| `eth2` | LAN | Direct admin/client LAN |
| `eth3` | LAN-DHCP/home-router | Connect your home Wi-Fi router WAN port here |
| `wwan0` | 4G backup | SIM/LTE failover |

`eth2` and `eth3` are bridged into `br-lan`. NexusGate runs DHCP on LAN, so your home Wi-Fi router can plug into `eth3` and receive internet.

Recommended Wi-Fi router mode:

- Best: Access Point / bridge mode, DHCP off.
- OK: Router mode, WAN via DHCP from NexusGate on `eth3`.

## Web UI access

OpenMPTCProuter/OpenWrt already includes LuCI web UI.

From LAN / Wi-Fi router side:

```text
http://192.168.100.1
https://192.168.100.1
```

Default service ports on router:

| Service | Port | URL |
|---|---:|---|
| LuCI HTTP | 80 | `http://192.168.100.1` |
| LuCI HTTPS | 443 | `https://192.168.100.1` |
| SSH | 22 | `ssh root@192.168.100.1` |
| OMR admin API | 65500 | internal/admin only |

Install LuCI addons:

```bash
scripts/install-luci-addons.sh
```

Installed UI modules:

- `luci-app-mwan3`
- `luci-app-sqm`
- `luci-app-statistics`
- `luci-app-vnstat`
- `luci-app-firewall`
- `luci-app-commands`
- 4G modem LuCI protocols
- OMR bypass UI when available

## Important limit

A single TCP flow cannot be split across two WANs without MPTCP multipath. Multi-flow operations can use both WANs.

## Quick start

1. Follow `prompts/00-bootstrap.md` through `prompts/13-verification.md`.
2. Install LuCI addons via `scripts/install-luci-addons.sh`.
3. Configure LAN bridge/DHCP via `scripts/configure-lan-eth3.sh`.
4. Configure operation-aware balancing via `scripts/configure-load-balancing.sh`.
5. Configure SQM via `scripts/configure-sqm.sh`.
6. Configure sticky exceptions via `scripts/configure-bypass.sh`.

## Modes

- **Operation-aware SD-WAN (default)**: mwan3 per-flow balancing; sticky only for sensitive traffic.
- **Device/App Policy Routing**: optional overrides.
- **Advanced multipath**: MPTCP/OMR endpoint support for single-flow >1Gb scenarios.

License: MIT.
