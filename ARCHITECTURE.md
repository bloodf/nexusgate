# Architecture

NexusGate is operation-aware SD-WAN/load-balancing first. Prompts/scripts/config overlay for OpenMPTCProuter/OpenWrt, native LuCI/OMR web UI.

## Core principle

NexusGate balances by **operation/flow**, not by machine. One LAN device can use both 1Gb WANs at the same time when its workload opens multiple flows.

Single TCP/UDP flow cannot be split across two WANs without bonding/MPTCP. Per-operation multi-flow distribution; latency-sensitive traffic pinning planned for roadmap.

## Topology

- `eth0` → LAN / management; bridged with eth3 in `br-lan`
- `eth1` → WAN1 (primary, e.g. PPPoE/fiber) via GPON ONT or fiber modem
- `eth2` → WAN2 (secondary, e.g. DHCP/cable) via cable modem in bridge mode (carrier address direct, possibly CGNAT) or router mode (double-NAT); reference deployment uses bridge
- `eth3` → LAN downlink to home Wi-Fi router; bridged with eth0
- No wwan0 / 4G in v1

## Default mode: ECMP SD-WAN

mwan3 unsupported on OMR (`iptables-mod-conntrack-extra` missing on nftables-only OMR 6.6).

Replacement: kernel ECMP multipath in OMR's existing balanced routing table `991337`.

- Post-tracking hook `/usr/share/omr/post-tracking.d/099-ecmp-balance` rebuilds 991337 with two nexthops, sourced from per-WAN tables (table 6 = wan1, table 10 = wan2). OMR sets `defaultroute=0`, so `ubus call network.interface.wanX status` returns empty route arrays; read tables 6/10 directly.
- `ip rule add priority 50 iif br-lan lookup 991337` forces LAN-forwarded traffic into 991337 (main table otherwise pins to lowest-metric default).
- `net.ipv4.fib_multipath_hash_policy=1` enables L4 hash (src+dst port). Default L3-only hash pins single client→single server to one WAN forever.
- Persisted via `/etc/sysctl.d/99-ecmp.conf` and `/etc/rc.local`.

## Policy engine (roadmap)

Sticky exceptions (gaming/VoIP/banking) via OMR bypass / fwmark rules. Not active in v1 ECMP-only baseline.

## Remote access (Tailscale)

Router runs `tailscaled` as a separate ingress path. Joins tailnet as `nexusgate`, advertises `192.168.100.0/24` subnet route, exposes Tailscale SSH on its `100.x.y.z` tailnet IP.

- Tailscale interface: `tailscale0` (WireGuard-over-UDP, peer-discovered via DERP relays + NAT punch).
- Egress from router: uses normal main-table default (independent of ECMP table 991337). No interference with WAN load balancing.
- Ingress from tailnet: SSH/LuCI/AdGuard UI reachable on tailnet IP from any approved peer, anywhere.
- Subnet routing: peers with `--accept-routes` reach LAN clients (e.g. `192.168.100.50`) without being on LAN physically.
- DNS: `--accept-dns=false` keeps AdGuard as authoritative LAN resolver; tailnet MagicDNS off.

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
        +-----------------------+
        |   NexusGate (OMR)     |
        |                       |
        |  ECMP table 991337    |   <-- L4 hash, per-flow nexthop
        |  + ip rule iif br-lan |
        |  + post-tracking hook |
        |                       |
        |  dnsmasq :53 (LAN)    |
        |   -> 127.0.0.1:5354   |
        |       AdGuard Home    |   <-- 4 filter lists
        |       -> upstream DoH |
        |                       |
        |  tailscale0 (WG/UDP)  |   <-- ingress from anywhere
        |   advertises          |
        |   192.168.100.0/24    |
        +-----------------------+
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

## Web UI

- `luci-app-sqm` for CAKE.
- `luci-app-statistics` / `luci-app-vnstat` for graphs/accounting.
- OMR LuCI pages for multipath and bypass controls.

## Advanced multipath

OpenMPTCProuter can use MPTCP/ShadowSocks/Glorytun for advanced single-flow multipath with external endpoint. Kept separate from default SD-WAN policy.

## Limits

- Single TCP download from a single-connection server → one WAN.
- One machine multi-flow → up to ~2Gb aggregate.
- MPTCP useless against non-MPTCP peers; ECMP covers the common case.
