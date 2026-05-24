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

## Expected behavior

| Workload | Result |
|---|---|
| One TCP flow | one WAN max (one ECMP bucket) |
| Multi-stream speedtest | WAN1+WAN2 aggregate (multiple buckets) |
| Steam/browser/package downloads | often WAN1+WAN2 aggregate |
| Gaming/VoIP (v1) | balanced like any flow; sticky roadmap |
| WAN failure | post-tracking hook rebuilds 991337 with surviving nexthop |
