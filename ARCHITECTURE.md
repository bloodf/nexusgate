# Architecture

NexusGate is a dual-WAN home router providing per-device WAN affinity. Prompts/scripts/config
overlay for OpenMPTCProuter/OpenWrt, native LuCI/OMR web UI.

## Core principle

Each LAN device egresses via exactly **one WAN** and keeps **one stable public IP**. Both WAN
links carry traffic in parallel across devices (offload), but a single device is pinned to one
link. This eliminates the streaming/gaming breakage that per-flow ECMP caused: L4-hashing one
device across two public IPs breaks TLS session resume, QUIC migration, and anti-fraud checks.

## Topology

- `eth0` - LAN / management; bridged with eth3 in `br-lan`
- `eth1` - WAN1 (primary, e.g. PPPoE/fiber) via GPON ONT or fiber modem
- `eth2` - WAN2 (secondary, e.g. DHCP/cable) via cable modem in bridge mode (carrier address
  direct, possibly CGNAT) or router mode (double-NAT); reference deployment uses bridge
- `eth3` - LAN downlink to home Wi-Fi router; bridged with eth0
- No wwan0 / 4G in v1

`br-lan` = eth0 + eth3. LAN subnet: `192.168.100.0/24`.

## Per-device WAN affinity (active routing model)

**WAN1 (primary) is the default WAN** for every LAN device. Devices whose MAC is in the WAN2
lock list egress WAN2 (secondary). Applied by `scripts/configure-wan-affinity.sh` and managed
via the web UI at `http://192.168.100.1/cgi-bin/wan-affinity`.

### Marks, rules, tables

| Selector | nft mark | ip rule priority | Table | Primary nexthop | Failover |
|---|---|---|---|---|---|
| WAN2-locked MAC | `0x20000` | 41 | 101 | WAN2 (`eth2`) | WAN1 (`pppoe-wan1`) |
| WAN1-locked MAC | `0x10000` | 40 | 100 | WAN1 (`pppoe-wan1`) | WAN2 (`eth2`) |
| Unmarked LAN | - | 45 `iif br-lan` | 100 | WAN1 (default) | WAN2 |

- **Marking** is an nft prerouting chain `/etc/nftables.d/20-wan-affinity.nft` (priority -150),
  keyed on `ether saddr`. No jhash, no port folding.
- **Each table holds a single nexthop** - a device's flows never split across two public IPs.
- **Failover + shift-back** lives in post-tracking hook `098-wan-affinity`: each omr-tracker
  tick it rewrites the single nexthop of tables 100/101 from live WAN state. On WAN recovery
  the device shifts back automatically (one brief reconnect per switch).
- Gateways sourced from OMR per-WAN tables 6 (wan1) and 10 (wan2).
- **OMR core** still rebuilds its internal ECMP table `991337` and a `pri 50 iif br-lan lookup
  991337` rule every tick. The affinity LAN-default rule sits at **pri 45** (before 50),
  permanently shadowing it - no per-tick deletion race, survives OMR package upgrades.
  Table 991337 is OMR-internal; it is never the active routing path for LAN traffic.
- `multipath=off` on both WAN interfaces (MPTCP retired; no external VPS endpoint).
- **Gaming UDP** is pinned to WAN1 via OMR bypass (active, not roadmap).
- **Streaming** follows each device's affinity assignment - it is not bypassed.

## DNS

```text
LAN client :53 -> dnsmasq (192.168.100.1:53) -> AdGuard Home (127.0.0.1:5354)
                                                    -> filter lists
                                                    -> ISP plain DNS (policy-routed per WAN)
```

- dnsmasq handles LAN DHCP and forwards DNS to AdGuard.
- AdGuard upstream resolvers are ISP plain DNS; each resolver is policy-routed out its own WAN
  (WAN1 resolvers -> table 6; WAN2 resolvers -> table 10).

## SQM / CAKE

Both WANs shaped at 95% of plan rate for bufferbloat control. Applied per physical WAN interface
(`pppoe-wan1`, `eth2`), not on a tunnel.

## Remote access (Tailscale)

Router runs `tailscaled` as a separate ingress path. Joins tailnet as `nexusgate`.

- Tailscale interface: `tailscale0` (WireGuard-over-UDP, peer-discovered via DERP relays + NAT
  punch).
- Egress from router: uses the normal main-table default (independent of affinity tables 100/101).
  No interference with WAN affinity.
- Ingress from tailnet: SSH/LuCI/AdGuard UI reachable on tailnet IP from any approved peer.
- Subnet routing (opt-in): advertises `192.168.100.0/24` so tailnet peers can reach LAN clients.
- DNS: `--accept-dns=false` keeps AdGuard as authoritative LAN resolver; tailnet MagicDNS off.

## Policy engine

- **Gaming UDP bypass**: pinned to WAN1 via OMR bypass rules (active).
- **Per-device WAN lock**: WAN1 or WAN2 via MAC lock lists (active, managed via web UI).
- **Additional overrides**: optional per-app fwmark rules via OMR bypass.

## Web UI

- `luci-app-sqm` for CAKE.
- `luci-app-statistics` / `luci-app-vnstat` for graphs/accounting.
- OMR LuCI pages for bypass controls.
- Per-device WAN affinity web UI: `http://192.168.100.1/cgi-bin/wan-affinity` (OUI vendor
  lookup, device renaming, live conntrack rates).

## Full data flow

```text
                  Internet
                 /        \
        WAN1 (primary)    WAN2 (secondary)
        (e.g. PPPoE/fiber) (e.g. DHCP/cable)
            |                 |
       GPON ONT /        Cable/DSL Modem
       Fiber Modem        (bridge mode:
       (bridge)            carrier addr/CGNAT)
            |                 |
    pppoe-wan1 / eth1     eth2 / wan2
            \                 /
             \               /
              \             /
        +-----------------------------------------+
        |   NexusGate (OMR)                       |
        |                                         |
        |  nft prerouting: MAC -> mark 0x10000/   |
        |    0x20000 (/etc/nftables.d/            |
        |    20-wan-affinity.nft)                 |
        |                                         |
        |  ip rules:                              |
        |    pri 40: mark 0x10000 -> table 100    | <-- WAN1 single nexthop
        |    pri 41: mark 0x20000 -> table 101    | <-- WAN2 single nexthop
        |    pri 45: iif br-lan   -> table 100    | <-- unmarked LAN default (WAN1)
        |                                         |
        |  098-wan-affinity (post-tracking hook): |
        |    rewrites tables 100/101 nexthop      | <-- automatic failover + shift-back
        |    from live WAN state each tracker tick|
        |                                         |
        |  dnsmasq :53 (LAN)                      |
        |   -> 127.0.0.1:5354                     |
        |       AdGuard Home                      | <-- filter lists
        |       -> ISP DNS (policy-routed)        |
        |                                         |
        |  tailscale0 (WG/UDP)                    | <-- ingress from anywhere
        |   advertises 192.168.100.0/24 (opt-in)  |
        +-----------------------------------------+
              |          |
           eth0        eth3
        (admin PC)   (home Wi-Fi router,
                      AP mode preferred)
              \          /
               \        /
            br-lan 192.168.100.0/24
                    |
              LAN clients
              (DHCP from NexusGate)
```

## Limits

- A single device is capped at one WAN link (~1Gb) - 2Gb single-flow needs MPTCP+VPS bonding
  (out of scope; no VPS endpoint configured).
- No wwan0 / 4G in v1.
