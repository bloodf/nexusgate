# NexusGate

Open-source multi-WAN router for Intel i3 mini-PCs running OpenMPTCProuter/OpenWrt.

Default mode uses both 1Gb WAN links via **per-device WAN affinity**: each device
is assigned one WAN and keeps one stable public IP. Both links carry traffic in
parallel across devices (offload), and streaming/gaming stay stable because a
device's flows never split across two public IPs.

## Reference deployment

This project was built and tested on a Brazilian dual-ISP setup:
WAN1 (primary) = Vivo Fibra (PPPoE, generic credentials `cliente@cliente` / `cliente`),
WAN2 (secondary) = Claro Coaxial (DHCP/cable).
All ISP DNS addresses, public IPs, gateway addresses, the Tailscale node address, and
the previous-router references throughout these docs are example values from that
deployment. Replace them with your own region's providers, connection types,
credentials, and addresses.

## Default behavior

- Each device egresses **one WAN, one stable public IP** (no mid-session flip).
- **WAN1 (primary) is the default WAN**; a MAC lock list routes chosen devices
  (mostly streaming) over **WAN2 (secondary/fallback)**.
- Both WANs active simultaneously across devices; a single device is capped at one
  link (~1Gb) — 2Gb single-flow needs MPTCP+VPS bonding (out of scope).
- Automatic failover + shift-back per WAN (post-tracking hook `098-wan-affinity`).
- SQM/CAKE: low latency under load.

> Earlier releases used per-flow ECMP (L4 hash), which split one device across two
> public IPs and broke streaming/gaming. That model is retired
> (`scripts/ecmp-balance.sh` kept for history only).

## Ports / physical cabling

| Port | Role | Use |
|---|---|---|
| `eth0` | LAN / management | Admin PC; bridged with eth3 in br-lan |
| `eth1` | WAN1 (primary, e.g. PPPoE/fiber) | GPON ONT or fiber modem |
| `eth2` | WAN2 (secondary, e.g. DHCP/cable) | Cable modem in bridge mode (carrier address direct to eth2, possibly CGNAT) or router mode (double-NAT); reference deployment uses bridge |
| `eth3` | LAN downlink | Home Wi-Fi router WAN port; bridged with eth0 |

`eth0` and `eth3` are bridged into `br-lan`. NexusGate runs DHCP on LAN; home Wi-Fi router plugs into `eth3` and receives internet.

WAN1 PPPoE credentials: `<pppoe-username>` / `<pppoe-password>` (set by your ISP; see [Reference deployment](#reference-deployment) for the example values used during initial testing).

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

mwan3 unavailable on OMR (requires `iptables-mod-conntrack-extra`, missing on nftables-only system). Routing is per-device WAN affinity: an nft prerouting chain (`/etc/nftables.d/20-wan-affinity.nft`) marks each device by MAC, fwmark `ip rule`s send marked devices to single-nexthop tables 100 (WAN1) / 101 (WAN2), and post-tracking hook `/usr/share/omr/post-tracking.d/098-wan-affinity` handles failover. Applied by `scripts/configure-wan-affinity.sh`. (OMR core still maintains ECMP table 991337 but it is shadowed by the affinity rules.)

## Important limit

A single device is capped at one WAN link (~1Gb). Splitting one flow across two WANs needs MPTCP+VPS bonding (out of scope). Both WANs are used in parallel across different devices.

## Quick start

1. Follow `prompts/00-bootstrap.md` through `prompts/13-verification.md`.
2. Install LuCI addons via `scripts/install-luci-addons.sh`.
3. Configure LAN bridge (eth0+eth3) via `scripts/configure-lan-eth3.sh`.
4. Configure WAN1 PPPoE via `scripts/configure-wan-pppoe.sh` and WAN2 DHCP.
5. Configure per-device WAN affinity via `sh scripts/configure-wan-affinity.sh` (retires the old `ecmp-balance.sh` load balancer; set `WAN2_MACS`/`WAN1_MACS` to your lock lists).
6. Configure SQM via `scripts/configure-sqm.sh`.
7. Bootstrap AdGuard filter lists via `scripts/configure-adguard-filters.sh`.
8. Point DNS at ISP resolvers via `scripts/configure-isp-dns.sh` and fix tracker ICMP false-down via `scripts/configure-omr-tracker.sh`.
9. (Optional) Enable remote admin via `scripts/configure-tailscale.sh` — see `prompts/14-tailscale.md`.

## Modes

- **Per-device WAN affinity (default)**: nft MAC marking + single-nexthop tables 100/101 + `098-wan-affinity` failover hook. One device = one WAN = one stable public IP.
- **Device/App Policy Routing**: optional overrides via OMR bypass / fwmark rules (roadmap).
- **Advanced multipath**: MPTCP/OMR endpoint support for single-flow >1Gb scenarios.

See `ARCHITECTURE.md` for full data-flow diagram and `docs/TAILSCALE.md` for remote-access details.

License: MIT.
