# Networking

NexusGate balances by operation/flow, not by machine.

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
| `eth1` | physical | (pppoe parent) | Fiber WAN physical |
| `pppoe-wan1` | pppoe | public IPv4 from Vivo | Fiber WAN logical |
| `eth2` | physical | private DHCP from cable modem | Coax WAN (double-NAT v1) |
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
