#!/bin/sh
set -eu
echo "Manual: unplug WAN1 (eth1) or WAN2 (eth2); the wan-affinity tracker rewrites the"
echo "single nexthop in table 100 (Vivo) or 101 (Claro) on each tick. Affected devices"
echo "shift to the surviving WAN automatically; each device keeps one stable IP."
echo "Re-plug to shift back."
echo "--- affinity tables (one nexthop each) ---"
ip route show table 100 || true
ip route show table 101 || true
echo "--- affinity ip rules ---"
ip rule show | grep -E "lookup (100|101)|iif br-lan" || true
