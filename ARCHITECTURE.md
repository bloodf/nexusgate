# Architecture

NexusGate is operation-aware SD-WAN/load-balancing first. The project is a prompts/scripts/config overlay for OpenMPTCProuter/OpenWrt and uses the native LuCI/OMR web UI.

## Core principle

NexusGate balances by **operation/flow**, not by machine. One LAN device can use both 1Gb WANs at the same time when its workload opens multiple flows, e.g. browsers, Steam, BitTorrent, cloud sync, multi-stream speed tests, package downloads, video apps.

A single TCP/UDP flow cannot be split across two WANs without bonding/MPTCP. NexusGate therefore optimizes for per-operation multi-flow distribution while pinning latency-sensitive traffic to one stable WAN.

## Topology

- `eth0` → WAN1 / `wan1`
- `eth1` → WAN2 / `wan2`
- `eth2` → LAN / `br-lan`
- `eth3` → LAN-DHCP/home Wi-Fi router uplink / `br-lan`
- `wwan0` → 4G backup / `wan3`

## Default mode: operation-aware SD-WAN

- `mwan3` distributes new flows across WAN1/WAN2 50/50.
- Sticky is disabled for normal/bulk/default traffic so one machine can open many flows across both WANs.
- Sticky is enabled only for gaming, VoIP, banking/login-sensitive destinations, and protocols that break on IP changes.
- Health checks remove failed/degraded WANs.
- WAN3/4G activates only as backup.

## Policy engine

- Gaming/VoIP → best latency WAN, sticky, no packet drops from WAN switching.
- Streaming → balanced WAN1/WAN2, optional domain stickiness when needed.
- Downloads/cloud backup/package managers → balanced per flow, no device pinning.
- Work/video calls → low-latency sticky policy.
- Guests/IoT → balanced or WAN2 preferred.
- Unknown/general → balanced 50/50, non-sticky.

## Web UI

Use built-in OpenMPTCProuter/OpenWrt LuCI:

- `luci-app-mwan3` for WAN balancing/failover.
- `luci-app-sqm` for CAKE.
- `luci-app-statistics` / `luci-app-vnstat` for graphs/accounting.
- OMR LuCI pages for multipath and bypass controls.

## Advanced multipath

OpenMPTCProuter can use MPTCP/ShadowSocks/Glorytun for advanced single-flow multipath scenarios when an external endpoint is configured. NexusGate keeps this separate from the default SD-WAN policy.

## Limits

- One single TCP download from a server that uses exactly one connection → max one WAN.
- One machine with multi-flow workloads → can use both WANs up to ~2Gb aggregate.
- Gaming/VoIP → intentionally pinned to one WAN for stability.
