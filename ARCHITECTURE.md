# Architecture

NexusGate is operation-aware SD-WAN/load-balancing first. Prompts/scripts/config overlay for OpenMPTCProuter/OpenWrt, native LuCI/OMR web UI.

## Core principle

NexusGate balances by **operation/flow**, not by machine. One LAN device can use both 1Gb WANs at the same time when its workload opens multiple flows.

Single TCP/UDP flow cannot be split across two WANs without bonding/MPTCP. Per-operation multi-flow distribution; latency-sensitive traffic pinning planned for roadmap.

## Topology

- `eth0` → LAN / management; bridged with eth3 in `br-lan`
- `eth1` → WAN1 Fiber PPPoE (Vivo Fibra via TP-Link GPON ONT)
- `eth2` → WAN2 Coax DHCP (cable modem in router mode, double-NAT v1)
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
