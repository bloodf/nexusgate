# Traffic Classification

Goal: stable per-device egress with predictable latency for real-time traffic.

## Default: per-device WAN affinity

Every LAN device egresses one WAN (one stable public IP). WAN assignment is by MAC:

- Unmarked devices -> WAN1 (primary, default).
- Devices in the WAN2 lock list -> WAN2 (secondary).
- Devices in the WAN1 lock list -> WAN1 (explicitly pinned).

Manage lock lists via `http://10.25.0.1/cgi-bin/wan-affinity` or by re-running
`scripts/configure-wan-affinity.sh` with updated `CLARO_MACS` / `VIVO_MACS`.

## Gaming UDP (WAN1 pin via OMR bypass)

Gaming and VoIP traffic is pinned to WAN1 via OMR bypass rules (active). Ports:

- UDP 3074 (Xbox Live / CoD)
- UDP 3478-3480 (PSN / WebRTC / STUN)
- UDP 3659 (Apple Game Center)
- UDP 27000-27100 (Steam)
- SIP 5060-5061
- RTP 10000-20000

Reason: changing WAN/public IP mid-session causes packet loss, jitter, NAT breakage,
or disconnects. Pinning to WAN1 guarantees a stable IP regardless of device affinity.

## Optional sticky overrides

Add additional OMR bypass / fwmark rules for banking, SSO, payment processors, work
VPNs, or video call services if sessions break on WAN shifts.

## What is NOT done

- No per-flow load balancing (L4 hash / ECMP) - retired; it broke streaming/gaming.
- No MPTCP bonding - out of scope; no VPS endpoint configured.
- Streaming traffic is NOT bypassed - it follows each device's affinity assignment,
  which gives it a stable IP (sufficient for all major streaming platforms).
