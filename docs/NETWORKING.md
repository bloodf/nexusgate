# Networking

NexusGate balances by operation/flow, not by machine.

## LAN topology (eth3 → unmanaged switch)

`eth3` is the LAN trunk to a TP-Link 1Gb unmanaged switch. All downstream devices share `192.168.100.0/24`.

| Switch port | Device | Notes |
|---:|---|---|
| 1 | TP-Link Deco BE65 (main) | AP mode; other 4 Decos mesh wirelessly |
| 2 | CortexOS local VPS | Reserved `192.168.100.10` (MAC `40:9c:a7:49:4b:62`) |
| 3 | WD NAS | Dynamic; firmware-configured static `.187` left in place |

Deco mesh (5x BE65) is in **Access Point mode**: all 5 Decos pull DHCP from NexusGate, all Wi-Fi clients land directly on `192.168.100.0/24`, AdGuard sees every query, ECMP balances every flow. Reservations intentionally not used for Decos.

DHCP pool = `192.168.100.50-249`. Static infra range `2-49` reserved.
DNS push (DHCP option 6) = `192.168.100.1` so every client uses the dnsmasq → AdGuard chain.

## SQM / CAKE

Both WANs shaped at 95% of plan for bufferbloat control:

| WAN | Interface | Down (Kbps) | Up (Kbps) | Linklayer | Overhead |
|---|---|---:|---:|---|---:|
| Vivo Fibra (1G/500M) | `pppoe-wan1` | 950 000 | 475 000 | ethernet | 44 (PPPoE) |
| Claro Coaxial (1G/100M) | `eth2` | 950 000 | 95 000 | ethernet | 18 (DOCSIS) |

Apply via `scripts/configure-sqm.sh` (override per env vars). CAKE shapes ingress via `ifb4*` interfaces automatically.

## Tailscale DNS intercept

Removed Tailscale leaves clients with `100.100.100.100` in their static DNS config — those packets get routed to the public Internet and dropped. `scripts/configure-dns-intercept.sh` installs an `fw4` DNAT rule that rewrites `100.100.100.100:53` (UDP+TCP) → `192.168.100.1:53` (dnsmasq → AdGuard), so clients keep working without reconfiguration.

## Default policy: kernel ECMP

- Kernel multipath in OMR table `991337` with two equal-cost nexthops (wan1, wan2).
- Per-WAN defaults sourced from tables 6 (wan1) and 10 (wan2) by post-tracking hook `099-ecmp-balance`.
- LAN traffic forced into 991337 via `ip rule ... iif br-lan lookup 991337`.
- Requires `net.ipv4.fib_multipath_hash_policy=1` (L4 hash incl. src+dst port). Default L3-only hash would pin one LAN client → one server to a single WAN.
- 4G/wan3 backup: out of scope v1.
- Sticky exceptions: roadmap (OMR bypass / fwmark rules).

One PC can use both links when it opens multiple connections (different src/dst ports → different ECMP buckets).

## Sticky exceptions (roadmap, not v1)

Will be applied via OMR bypass or fwmark rules for:

- Gaming UDP
- VoIP/SIP/RTP
- Video calls if needed
- Banking/login-sensitive domains

## Interface map

| Interface | Type | Subnet / addr | Role |
|---|---|---|---|
| `eth0` | physical | (in br-lan) | LAN/mgmt port; bridged |
| `eth3` | physical | (in br-lan) | LAN downlink to home Wi-Fi router; bridged |
| `br-lan` | bridge | 192.168.100.1/24 | LAN side, DHCP server |
| `eth1` | physical | (pppoe parent) | Vivo Fibra WAN physical |
| `pppoe-wan1` | pppoe | public IPv4 from Vivo | Vivo Fibra WAN logical (label: "Vivo Fibra") |
| `eth2` | physical | private DHCP from Claro cable modem | Claro Coaxial WAN (double-NAT v1, label: "Claro Coaxial") |
| `tailscale0` | wireguard | 100.x.y.z/32 | Tailnet ingress + subnet route |

## Traffic flow matrix

| Source | Destination | Path | Table |
|---|---|---|---|
| LAN client | Internet | br-lan -> ip rule iif br-lan -> ECMP (per-flow nexthop) -> pppoe-wan1 or eth2 | 991337 |
| Router itself | Internet | main default (lowest metric) | main |
| LAN client | LAN client | br-lan switching, no IP routing | n/a |
| LAN client | NexusGate LuCI/SSH | direct on br-lan to 192.168.100.1 | local |
| Tailnet peer | NexusGate LuCI/SSH | tailscale0 to 100.x.y.z | local |
| Tailnet peer | LAN client | tailscale0 -> br-lan (subnet route) | main |
| NexusGate | Tailnet peer (DERP/keepalive) | main default | main |
| LAN client (DNS) | dnsmasq :53 | br-lan -> dnsmasq -> 127.0.0.1:5354 (AdGuard) -> DoH upstream | local + WAN |

## DNS chain

```text
LAN client :53 -> dnsmasq (router :53) -> AdGuard Home (127.0.0.1:5354)
                                              -> filter lists (block ads/trackers)
                                              -> DoH upstream (Cloudflare/Google)
```

AdGuard filter lists bootstrapped by `scripts/configure-adguard-filters.sh` (AdGuard DNS filter, AdAway, Tracking Protection, Popup Hosts).

## Expected behavior

| Workload | Result |
|---|---|
| One TCP flow | one WAN max (one ECMP bucket) |
| Multi-stream speedtest | WAN1+WAN2 aggregate (multiple buckets) |
| Steam/browser/package downloads | often WAN1+WAN2 aggregate |
| Gaming/VoIP (v1) | balanced like any flow; sticky roadmap |
| WAN failure | post-tracking hook rebuilds 991337 with surviving nexthop |
