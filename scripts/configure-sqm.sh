#!/bin/sh
# Configure SQM/CAKE on both WANs.
#
# Defaults match deployed plan: Vivo Fibra 1G/500M (PPPoE, overhead 44),
# Claro Coaxial 1G/100M (DOCSIS Ethernet, overhead 18). Shapes at 95% of plan
# to leave headroom for CAKE to actually control the queue.
#
# Override via env:
#   WAN1_DOWN, WAN1_UP, WAN1_OVERHEAD     # Vivo Fibra (PPPoE on pppoe-wan1)
#   WAN2_DOWN, WAN2_UP, WAN2_OVERHEAD     # Claro Coaxial (DHCP on eth2)
#
# Note: shape on the actual L2/L3 interface (pppoe-wan1, eth2), not the UCI
# section name. CAKE on a logical 'wan1' interface name shapes nothing.

set -eu

WAN1_IF=${WAN1_IF:-pppoe-wan1}
WAN1_DOWN=${WAN1_DOWN:-950000}
WAN1_UP=${WAN1_UP:-475000}
WAN1_OVERHEAD=${WAN1_OVERHEAD:-44}

WAN2_IF=${WAN2_IF:-eth2}
WAN2_DOWN=${WAN2_DOWN:-950000}
WAN2_UP=${WAN2_UP:-95000}
WAN2_OVERHEAD=${WAN2_OVERHEAD:-18}

opkg update
opkg install sqm-scripts luci-app-sqm || true

uci -q delete sqm.wan1 || true
uci -q delete sqm.wan2 || true

uci set sqm.wan1=queue
uci set sqm.wan1.enabled=1
uci set sqm.wan1.interface="$WAN1_IF"
uci set sqm.wan1.download="$WAN1_DOWN"
uci set sqm.wan1.upload="$WAN1_UP"
uci set sqm.wan1.qdisc=cake
uci set sqm.wan1.script=piece_of_cake.qos
uci set sqm.wan1.qdisc_advanced=1
uci set sqm.wan1.linklayer=ethernet
uci set sqm.wan1.overhead="$WAN1_OVERHEAD"
uci set sqm.wan1.squash_dscp=0
uci set sqm.wan1.squash_ingress=0

uci set sqm.wan2=queue
uci set sqm.wan2.enabled=1
uci set sqm.wan2.interface="$WAN2_IF"
uci set sqm.wan2.download="$WAN2_DOWN"
uci set sqm.wan2.upload="$WAN2_UP"
uci set sqm.wan2.qdisc=cake
uci set sqm.wan2.script=piece_of_cake.qos
uci set sqm.wan2.qdisc_advanced=1
uci set sqm.wan2.linklayer=ethernet
uci set sqm.wan2.overhead="$WAN2_OVERHEAD"
uci set sqm.wan2.squash_dscp=0
uci set sqm.wan2.squash_ingress=0

uci commit sqm

/etc/init.d/sqm enable
/etc/init.d/sqm restart

echo
echo "== CAKE qdiscs =="
tc qdisc show | grep -E "cake" | head -10
