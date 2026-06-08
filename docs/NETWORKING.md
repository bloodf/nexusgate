# Networking

NexusGate assigns each device to one WAN (per-device affinity), giving every
device a single stable public IP. It no longer balances per-flow — see
[Default policy: per-device WAN affinity](#default-policy-per-device-wan-affinity).

## LAN topology (eth3 → unmanaged switch)

`eth3` is the LAN trunk to a TP-Link 1Gb unmanaged switch. All downstream devices share `192.168.100.0/24`.

| Switch port | Device | Notes |
|---:|---|---|
| 1 | TP-Link Deco BE65 (main) | AP mode; other 4 Decos mesh wirelessly |
| 2 | CortexOS local VPS | Reserved `192.168.100.10` (MAC `40:9c:a7:49:4b:62`) |
| 3 | WD NAS | Dynamic; firmware-configured static `.187` left in place |

Deco mesh (5x BE65) is in **Access Point mode**: all 5 Decos pull DHCP from NexusGate, all Wi-Fi clients land directly on `192.168.100.0/24`, AdGuard sees every query, and per-device WAN affinity (by client MAC) decides each device's egress WAN. Reservations intentionally not used for Decos.

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

## Default policy: per-device WAN affinity

Each device egresses one WAN and keeps one stable public IP. This replaced the
old per-flow ECMP balancer, which L4-hashed a single device's connections across
both public IPs at once and broke streaming/gaming (TLS resume failures, QUIC
migration rejected, anti-fraud resets). Apply via `scripts/configure-wan-affinity.sh`.

**Model**

- **Vivo (wan1) is the default WAN** for every LAN device.
- Devices whose MAC is in the **Claro lock list** egress Claro (wan2) — mostly
  streaming boxes (Claro's ~950M down suits streaming; weak up is irrelevant for
  download). Devices in the **Vivo lock list** are explicitly pinned to Vivo.
- Both WANs carry traffic simultaneously across devices (offload, not single-flow
  aggregation). A single device is capped at one link (~1Gb); 2Gb single-flow is
  impossible without MPTCP+VPS bonding, which is out of scope.

**Marks, rules, tables**

| Selector | Mark | `ip rule` | Table | Primary nexthop | Failover |
|---|---|---|---|---|---|
| Claro-locked MAC | `0x20000` | pri 41 | 101 | Claro (`eth2`) | Vivo (`pppoe-wan1`) |
| Vivo-locked MAC | `0x10000` | pri 40 | 100 | Vivo (`pppoe-wan1`) | Claro (`eth2`) |
| unmarked LAN | — | pri 45 `iif br-lan` | 100 | Vivo (default) | Claro |

- Marking is an nft prerouting chain (`/etc/nftables.d/20-wan-affinity.nft`,
  priority -150) keyed on `ether saddr`. No `jhash`, no port folding.
- Each table holds a **single nexthop**, so a device's flows never split across
  two public IPs mid-session — this is what keeps streaming/gaming stable.
- **Failover + shift-back** lives in post-tracking hook `098-wan-affinity`: each
  omr-tracker tick it rewrites the single nexthop of tables 100/101 from live WAN
  state (`openmptcprouter.wanN.state`). Marks never change, so a device returns to
  its home WAN automatically when that WAN recovers (one brief reset per switch).
- OMR core still rebuilds its ECMP table `991337` and a `pri 50 iif br-lan lookup
  991337` rule every tick. The affinity LAN-default rule sits at **pri 45**
  (before 50), permanently shadowing it — no per-tick deletion race, survives OMR
  package upgrades. `fib_multipath_hash_policy` is left as-is but unused.
- NAT: the fw4 wan-zone masquerade SNATs per egress device, so both tables get
  correct source NAT with no extra config.
- 4G/wan3 backup: out of scope.

To change a device's WAN, edit the lock lists and re-apply (see
[TROUBLESHOOTING](TROUBLESHOOTING.md)), or use the device-management WebUI.

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
| LAN client (default) | Internet | br-lan -> ip rule pri 45 iif br-lan -> single nexthop -> pppoe-wan1 (Vivo) | 100 |
| LAN client (Claro-locked) | Internet | br-lan -> nft mark 0x20000 -> ip rule pri 41 -> single nexthop -> eth2 (Claro) | 101 |
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

Upstream resolvers are ISP plain DNS only (no Cloudflare/Google/Quad9 DoH). Apply via `scripts/configure-isp-dns.sh`; each resolver is policy-routed out its own WAN (Vivo → table 6, Claro → table 10).

## Expected behavior

| Workload | Result |
|---|---|
| Any flow from one device | one WAN, one stable public IP (no mid-session flip) |
| Single-device speedtest | capped at that device's WAN (~1Gb), not aggregate |
| Two devices on different WANs | both links carry traffic in parallel (offload) |
| Streaming/gaming | stable — single egress IP, no TLS-resume/QUIC breakage |
| WAN failure | `098-wan-affinity` repoints affected table to surviving WAN next tick; devices shift back on recovery |
