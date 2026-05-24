# 05 Operation-Aware Load Balancing Setup

## Goal
Configure NexusGate so one machine can use both WANs across multiple operations/flows, while gaming/VoIP stay pinned to one WAN.

## Model

- Default traffic: per-flow balanced WAN1/WAN2, sticky disabled.
- Gaming/VoIP: sticky enabled, low-latency WAN preferred.
- 4G: backup only.
- No VPS required.

## Actions

1. Confirm WAN1/WAN2 have internet.
2. Run `scripts/configure-load-balancing.sh` on router (kernel ECMP, table 991337; mwan3 unsupported on OMR).
3. Verify `ip route show table 991337` shows two nexthops and `sysctl net.ipv4.fib_multipath_hash_policy` returns 1.
4. Run multi-flow speed test from one machine.
5. Confirm gaming/VoIP rules have `sticky=1`.

## Verification

- Multi-flow speed test can exceed one WAN speed.
- Single-flow test stays near one WAN speed by design.
- Gaming UDP traffic uses sticky low-latency policy.
- Failover removes dead WAN.

## Checkpoint
One PC with multi-flow workload can consume both 1Gb links; gaming/VoIP remain stable on one WAN.
