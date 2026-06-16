# Networking

NexusGate assigns each device to one WAN (per-device affinity), giving every
device a single stable public IP. It no longer balances per-flow — see
[Default policy: per-device WAN affinity](#default-policy-per-device-wan-affinity).

## LAN topology (eth3 → unmanaged switch)

`eth3` is the LAN trunk to a TP-Link 1Gb unmanaged switch. All downstream devices share `10.25.0.0/16`.

| Switch port | Device | Notes |
|---:|---|---|
| 1 | TP-Link Deco BE65 (main) | AP mode; other 4 Decos mesh wirelessly |
| 2 | CortexOS local VPS | Reserved `10.25.0.10` (MAC `40:9c:a7:49:4b:62`) |
| 3 | WD NAS | Dynamic; firmware-configured static `.187` left in place |

Deco mesh (5x BE65) is in **Access Point mode**: all 5 Decos pull DHCP from NexusGate, all Wi-Fi clients land directly on `10.25.0.0/16`, AdGuard sees every query, and per-device WAN affinity (by client MAC) decides each device's egress WAN. Reservations intentionally not used for Decos.

DHCP pool = `10.25.1.1-` (~60000 leases). `10.25.0.0/24` reserved for router (`10.25.0.1`) + static/infra.
DNS push (DHCP option 6) = `10.25.0.1` so every client uses the dnsmasq → AdGuard chain.

## SQM / CAKE

Both WANs shaped at 95% of plan for bufferbloat control:

| WAN | Interface | Down (Kbps) | Up (Kbps) | Linklayer | Overhead |
|---|---|---:|---:|---|---:|
| WAN1 (primary, e.g. PPPoE/fiber 1G/500M) | `pppoe-wan1` | 950 000 | 475 000 | ethernet | 44 (PPPoE) |
| WAN2 (secondary, e.g. DHCP/cable 1G/100M) | `eth2` | 950 000 | 95 000 | ethernet | 18 (DOCSIS) |

Values shown are from the [reference deployment](../README.md#reference-deployment). Override via env vars when running `scripts/configure-sqm.sh`. CAKE shapes ingress via `ifb4*` interfaces automatically.

## Tailscale DNS intercept

Removed Tailscale leaves clients with `100.100.100.100` in their static DNS config — those packets get routed to the public Internet and dropped. `scripts/configure-dns-intercept.sh` installs an `fw4` DNAT rule that rewrites `100.100.100.100:53` (UDP+TCP) → `10.25.0.1:53` (dnsmasq → AdGuard), so clients keep working without reconfiguration.

## Default policy: per-device WAN affinity

Each device egresses one WAN and keeps one stable public IP. This replaced the
old per-flow ECMP balancer, which L4-hashed a single device's connections across
both public IPs at once and broke streaming/gaming (TLS resume failures, QUIC
migration rejected, anti-fraud resets). Apply via `scripts/configure-wan-affinity.sh`.

**Model**

- **WAN1 (primary) is the default WAN** for every LAN device.
- Devices whose MAC is in the **WAN2 lock list** egress WAN2 (secondary) — e.g.
  streaming boxes where WAN2's high downstream bandwidth suits the load; weak
  upload is irrelevant for download workloads. Devices in the **WAN1 lock list**
  are explicitly pinned to WAN1.
- Both WANs carry traffic simultaneously across devices (offload, not single-flow
  aggregation). A single device is capped at one link (~1Gb); 2Gb single-flow is
  impossible without MPTCP+VPS bonding, which is out of scope.

**Marks, rules, tables**

| Selector | Mark | `ip rule` | Table | Primary nexthop | Failover |
|---|---|---|---|---|---|
| WAN2-locked MAC | `0x20000` | pri 41 | 101 | WAN2 (`eth2`) | WAN1 (`pppoe-wan1`) |
| WAN1-locked MAC | `0x10000` | pri 40 | 100 | WAN1 (`pppoe-wan1`) | WAN2 (`eth2`) |
| unmarked LAN | — | pri 45 `iif br-lan` | 100 | WAN1 (default) | WAN2 |

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

**WebUI features (v2)**

- **OUI vendor lookup** - for devices with no DHCP hostname or custom name, the
  UI shows the hardware vendor derived from an offline IEEE OUI database
  (`/usr/lib/wan-affinity/oui.db`, ~39 000 entries, deployed by the installer).
  No network call is made; lookup is a single awk pass on the ~1 MB local file.
- **Device renaming** - click the pencil icon next to any device name to assign
  a persistent friendly name. Names are stored in `/etc/wan-affinity/names.list`
  (format: `mac|name`, one per line) and survive reboots. Renaming does not
  affect routing and does not call `apply-affinity.sh`.
- **Live per-device bandwidth** - the device table includes Down and Up columns
  showing current throughput in kb/s or Mb/s. Rates are computed server-side
  from two conntrack snapshots ~1 s apart (single awk pass each); no background
  daemon is required. Each page refresh takes ~1 s. A "Live" checkbox enables
  3 s auto-refresh for continuous monitoring.

## Interface map

| Interface | Type | Subnet / addr | Role |
|---|---|---|---|
| `eth0` | physical | (in br-lan) | LAN/mgmt port; bridged |
| `eth3` | physical | (in br-lan) | LAN downlink to home Wi-Fi router; bridged |
| `br-lan` | bridge | 10.25.0.1/16 | LAN side, DHCP server |
| `eth1` | physical | (pppoe parent) | WAN1 (primary) physical port |
| `pppoe-wan1` | pppoe | public IPv4 from WAN1 ISP | WAN1 (primary) logical interface (label: "WAN1") |
| `eth2` | physical | carrier address via DHCP from WAN2 modem (may be CGNAT 100.64.0.0/10) | WAN2 (secondary) physical port (modem in bridge or router mode, label: "WAN2") |
| `tailscale0` | wireguard | 100.x.y.z/32 | Tailnet ingress + subnet route |

## Traffic flow matrix

| Source | Destination | Path | Table |
|---|---|---|---|
| LAN client (default) | Internet | br-lan -> ip rule pri 45 iif br-lan -> single nexthop -> pppoe-wan1 (WAN1) | 100 |
| LAN client (WAN2-locked) | Internet | br-lan -> nft mark 0x20000 -> ip rule pri 41 -> single nexthop -> eth2 (WAN2) | 101 |
| Router itself | Internet | main default (lowest metric) | main |
| LAN client | LAN client | br-lan switching, no IP routing | n/a |
| LAN client | NexusGate LuCI/SSH | direct on br-lan to 10.25.0.1 (any 10.25.x.y) | local |
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

Upstream resolvers are ISP plain DNS only (no Cloudflare/Google/Quad9 DoH). Apply via `scripts/configure-isp-dns.sh`; each resolver is policy-routed out its own WAN (WAN1 resolvers → table 6, WAN2 resolvers → table 10).

## Expected behavior

| Workload | Result |
|---|---|
| Any flow from one device | one WAN, one stable public IP (no mid-session flip) |
| Single-device speedtest | capped at that device's WAN (~1Gb), not aggregate |
| Two devices on different WANs | both links carry traffic in parallel (offload) |
| Streaming/gaming | stable — single egress IP, no TLS-resume/QUIC breakage |
| WAN failure | `098-wan-affinity` repoints affected table to surviving WAN next tick; devices shift back on recovery |
