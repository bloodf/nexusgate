#!/bin/sh
set -eu
WAN1_DOWN=${WAN1_DOWN:-950000}; WAN1_UP=${WAN1_UP:-950000}; WAN2_DOWN=${WAN2_DOWN:-950000}; WAN2_UP=${WAN2_UP:-950000}
opkg update; opkg install sqm-scripts luci-app-sqm || true
uci batch <<EOF
set sqm.wan1=queue
set sqm.wan1.interface='wan1'
set sqm.wan1.download='$WAN1_DOWN'
set sqm.wan1.upload='$WAN1_UP'
set sqm.wan1.qdisc='cake'
set sqm.wan1.script='piece_of_cake.qos'
set sqm.wan1.qdisc_advanced='1'
set sqm.wan1.squash_dscp='0'
set sqm.wan1.enabled='1'
set sqm.wan2=queue
set sqm.wan2.interface='wan2'
set sqm.wan2.download='$WAN2_DOWN'
set sqm.wan2.upload='$WAN2_UP'
set sqm.wan2.qdisc='cake'
set sqm.wan2.script='piece_of_cake.qos'
set sqm.wan2.qdisc_advanced='1'
set sqm.wan2.squash_dscp='0'
set sqm.wan2.enabled='1'
commit sqm
EOF
/etc/init.d/sqm enable; /etc/init.d/sqm restart
