#!/bin/sh
# /usr/share/omr/post-tracking.d/099-ecmp-balance
#
# Per-connection ECMP across both WANs in OMR's balanced table 991337.
# Fires on every omr-tracker tick. Idempotent.
#
# Why this exists:
#   - mwan3 will not install on OMR (nftables, no iptables-mod-conntrack-extra).
#   - OMR's built-in post-tracking scripts set a single nexthop in 991337 —
#     that is failover, not balancing.
#   - Cannot rely on ubus wan1/wan2 route arrays because OMR sets
#     defaultroute=0 on every WAN, so those arrays come back empty.
#     We instead source the gateway directly from each WAN's own table
#     (table 6 = wan1, table 10 = wan2), which OMR always populates.

set -eu

_omr_wan_up() {
	[ "$(uci -q get "openmptcprouter.${1}.state" 2>/dev/null)" = "up" ]
}

GW1=$(ip route show table 6  2>/dev/null | awk '/^default/ {print $3; exit}')
DEV1=$(ip route show table 6  2>/dev/null | awk '/^default/ {print $5; exit}')
GW2=$(ip route show table 10 2>/dev/null | awk '/^default/ {print $3; exit}')
DEV2=$(ip route show table 10 2>/dev/null | awk '/^default/ {print $5; exit}')

# Only balance WANs OMR tracker marks UP. A link-up / DHCP lease is not enough:
# when tracker marks DOWN, OMR poisons the per-WAN down table and traffic dies.
WAN1_OK=0
WAN2_OK=0
[ -n "${GW1:-}" ] && [ -n "${DEV1:-}" ] && _omr_wan_up wan1 && WAN1_OK=1
[ -n "${GW2:-}" ] && [ -n "${DEV2:-}" ] && _omr_wan_up wan2 && WAN2_OK=1

if [ "$WAN1_OK" = 1 ] && [ "$WAN2_OK" = 1 ]; then
	ip route replace default scope global table 991337 \
		nexthop via "$GW1" dev "$DEV1" weight 1 \
		nexthop via "$GW2" dev "$DEV2" weight 1
elif [ "$WAN1_OK" = 1 ]; then
	ip route replace default scope global table 991337 via "$GW1" dev "$DEV1"
elif [ "$WAN2_OK" = 1 ]; then
	ip route replace default scope global table 991337 via "$GW2" dev "$DEV2"
fi

# Force LAN-originated forwarded traffic into the balanced table. Without this
# rule the kernel falls back to the main table and pins everything to whichever
# default route has the lowest metric (eth2 in current deployment).
ip rule show | grep -q 'iif br-lan lookup 991337' \
	|| ip rule add priority 50 iif br-lan lookup 991337

# L4 hash. With the default L3-only policy, a single src IP -> dst IP pair
# always selects the same nexthop bucket, so a LAN client hitting one server
# (e.g. whatismyip.com) appears pinned to one WAN. L4 hashing folds the src
# port in, so concurrent flows from the same client to the same server spread
# across both WANs as intended.
sysctl -wq net.ipv4.fib_multipath_hash_policy=1 2>/dev/null || true
sysctl -wq net.ipv4.fib_multipath_use_neigh=1   2>/dev/null || true
