# NexusGate

Open-source operation-aware multi-WAN SD-WAN router for Intel i3 mini-PCs running OpenMPTCProuter/OpenWrt.

Default mode uses both 1Gb WAN links by balancing **operations/flows**, not machines. One PC can use both WANs simultaneously when apps open multiple connections.

## Default behavior

- Normal traffic: per-flow ECMP across WAN1/WAN2 (L4 hash).
- Downloads/package managers/cloud sync: spread flows across both WANs.
- One device can consume aggregate ~2Gb when workload is multi-flow.
- Sticky exceptions (gaming/VoIP/banking) are roadmap; not active in v1 baseline.
- SQM/CAKE: low latency under load.

## Ports / physical cabling

| Port | Role | Use |
|---|---|---|
| `eth0` | LAN / management | Admin PC; bridged with eth3 in br-lan |
| `eth1` | WAN1 Fiber (PPPoE) | TP-Link GPON ONT, Vivo Fibra |
| `eth2` | WAN2 Coax (DHCP) | Cable modem in router mode (double-NAT v1) |
| `eth3` | LAN downlink | Home Wi-Fi router WAN port; bridged with eth0 |

`eth0` and `eth3` are bridged into `br-lan`. NexusGate runs DHCP on LAN; home Wi-Fi router plugs into `eth3` and receives internet.

Vivo Fibra PPPoE credentials: `cliente@cliente` / `cliente` (generic; auth done at OLT by ONT serial).

No wwan0 / 4G in v1 deployment.

Recommended Wi-Fi router mode:

- Best: Access Point / bridge mode, DHCP off. Clients land directly on `192.168.100.0/24` and can reach NexusGate at `192.168.100.1` for LuCI/SSH — no need to plug into `eth0`.
- OK: Router mode, WAN via DHCP from NexusGate on `eth3`. Clients sit behind a second NAT; to admin NexusGate from those clients, either switch the home router to AP mode or use Tailscale (see below).

## Remote admin

- **From home Wi-Fi (no eth0 plug)**: put home router in AP/bridge mode and hit `http://192.168.100.1` from any Wi-Fi client.
- **From anywhere (over Internet)**: enable Tailscale via `scripts/configure-tailscale.sh`. Router joins tailnet, advertises `192.168.100.0/24`, exposes SSH+LuCI on its tailnet IP. See `prompts/14-tailscale.md`.

## Web UI access

OpenMPTCProuter/OpenWrt already includes LuCI web UI.

```text
http://192.168.100.1
https://192.168.100.1
```

Default service ports on router:

| Service | Port | URL / bind |
|---|---:|---|
| LuCI HTTP | 80 | `http://192.168.100.1` |
| LuCI HTTPS | 443 | `https://192.168.100.1` |
| SSH | 22 | `ssh root@192.168.100.1` |
| Client DNS (dnsmasq) | 53 | `192.168.100.1` LAN DNS/DHCP frontend |
| AdGuard Home UI | 3000 | `http://192.168.100.1:3000` |
| AdGuard Home DNS backend | 5354 | `127.0.0.1#5354` internal only |
| OMR admin API | 65500 | internal/admin only |

Install LuCI addons:

```bash
scripts/install-luci-addons.sh
```

Installed UI modules:

- `luci-app-sqm`
- `luci-app-statistics`
- `luci-app-vnstat`
- `luci-app-firewall`
- `luci-app-commands`
- OMR bypass UI when available
- `adguardhome` DNS filtering, with dnsmasq kept as LAN DHCP/DNS frontend

mwan3 unavailable on OMR (requires `iptables-mod-conntrack-extra`, missing on nftables-only system). Replaced by kernel ECMP via OMR's balanced routing table 991337, populated by post-tracking hook `/usr/share/omr/post-tracking.d/099-ecmp-balance`. Requires `net.ipv4.fib_multipath_hash_policy=1` for L4 hash so single LAN client to single server actually fans out across WANs.

## Important limit

A single TCP flow cannot be split across two WANs without MPTCP multipath. Multi-flow operations can use both WANs.

## Quick start

1. Follow `prompts/00-bootstrap.md` through `prompts/13-verification.md`.
2. Install LuCI addons via `scripts/install-luci-addons.sh`.
3. Configure LAN bridge (eth0+eth3) via `scripts/configure-lan-eth3.sh`.
4. Configure Fiber WAN PPPoE via `scripts/configure-wan-pppoe.sh` (Vivo Fibra) and Coax DHCP wan2.
5. Configure ECMP load balancing via `scripts/configure-load-balancing.sh`.
6. Configure SQM via `scripts/configure-sqm.sh`.
7. Bootstrap AdGuard filter lists via `scripts/configure-adguard-filters.sh`.
8. (Optional) Enable remote admin via `scripts/configure-tailscale.sh` — see `prompts/14-tailscale.md`.

## Modes

- **ECMP SD-WAN (default)**: kernel multipath in table 991337 + post-tracking hook; L4 hash.
- **Device/App Policy Routing**: optional overrides via OMR bypass / fwmark rules (roadmap).
- **Advanced multipath**: MPTCP/OMR endpoint support for single-flow >1Gb scenarios.

License: MIT.
