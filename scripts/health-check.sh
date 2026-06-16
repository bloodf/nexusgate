#!/bin/sh
set -eu
for h in 1.1.1.1 8.8.8.8; do ping -c 3 -W 1 "$h" >/dev/null && echo "$h ok" || echo "$h fail"; done
echo "--- affinity tables (one nexthop each) ---"
ip route show table 100 || true
ip route show table 101 || true
echo "--- per-WAN gateway tables ---"
ip route show table 6 || true
ip route show table 10 || true
echo "--- affinity ip rules ---"
ip rule show | grep -E "lookup (100|101)|iif br-lan" || true
