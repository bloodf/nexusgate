#!/bin/sh
set -eu

opkg update
opkg install mwan3 luci-app-mwan3 || true

uci batch <<'EOF'
# WAN health tracking
set mwan3.wan1=interface
set mwan3.wan1.enabled='1'
set mwan3.wan1.family='ipv4'
set mwan3.wan1.track_method='ping'
add_list mwan3.wan1.track_ip='1.1.1.1'
add_list mwan3.wan1.track_ip='8.8.8.8'
set mwan3.wan1.reliability='1'
set mwan3.wan1.count='3'
set mwan3.wan1.timeout='2'
set mwan3.wan1.interval='5'
set mwan3.wan1.down='3'
set mwan3.wan1.up='5'

set mwan3.wan2=interface
set mwan3.wan2.enabled='1'
set mwan3.wan2.family='ipv4'
set mwan3.wan2.track_method='ping'
add_list mwan3.wan2.track_ip='1.0.0.1'
add_list mwan3.wan2.track_ip='8.8.4.4'
set mwan3.wan2.reliability='1'
set mwan3.wan2.count='3'
set mwan3.wan2.timeout='2'
set mwan3.wan2.interval='5'
set mwan3.wan2.down='3'
set mwan3.wan2.up='5'

set mwan3.wan3=interface
set mwan3.wan3.enabled='1'
set mwan3.wan3.family='ipv4'
set mwan3.wan3.track_method='ping'
add_list mwan3.wan3.track_ip='9.9.9.9'
set mwan3.wan3.reliability='1'
set mwan3.wan3.down='3'
set mwan3.wan3.up='5'

# Members
set mwan3.wan1_m1_w50=member
set mwan3.wan1_m1_w50.interface='wan1'
set mwan3.wan1_m1_w50.metric='1'
set mwan3.wan1_m1_w50.weight='50'
set mwan3.wan2_m1_w50=member
set mwan3.wan2_m1_w50.interface='wan2'
set mwan3.wan2_m1_w50.metric='1'
set mwan3.wan2_m1_w50.weight='50'
set mwan3.wan1_m1_w100=member
set mwan3.wan1_m1_w100.interface='wan1'
set mwan3.wan1_m1_w100.metric='1'
set mwan3.wan1_m1_w100.weight='100'
set mwan3.wan2_m2_w1=member
set mwan3.wan2_m2_w1.interface='wan2'
set mwan3.wan2_m2_w1.metric='2'
set mwan3.wan2_m2_w1.weight='1'
set mwan3.wan2_m1_w100=member
set mwan3.wan2_m1_w100.interface='wan2'
set mwan3.wan2_m1_w100.metric='1'
set mwan3.wan2_m1_w100.weight='100'
set mwan3.wan1_m2_w1=member
set mwan3.wan1_m2_w1.interface='wan1'
set mwan3.wan1_m2_w1.metric='2'
set mwan3.wan1_m2_w1.weight='1'
set mwan3.wan3_m3_w1=member
set mwan3.wan3_m3_w1.interface='wan3'
set mwan3.wan3_m3_w1.metric='3'
set mwan3.wan3_m3_w1.weight='1'

# Policies
set mwan3.operation_balance=policy
add_list mwan3.operation_balance.use_member='wan1_m1_w50'
add_list mwan3.operation_balance.use_member='wan2_m1_w50'
add_list mwan3.operation_balance.use_member='wan3_m3_w1'

set mwan3.low_latency_wan1=policy
add_list mwan3.low_latency_wan1.use_member='wan1_m1_w100'
add_list mwan3.low_latency_wan1.use_member='wan2_m2_w1'
add_list mwan3.low_latency_wan1.use_member='wan3_m3_w1'

set mwan3.low_latency_wan2=policy
add_list mwan3.low_latency_wan2.use_member='wan2_m1_w100'
add_list mwan3.low_latency_wan2.use_member='wan1_m2_w1'
add_list mwan3.low_latency_wan2.use_member='wan3_m3_w1'

# Default: operation/flow balancing. Sticky OFF so one machine with many flows can use both WANs.
set mwan3.default_rule=rule
set mwan3.default_rule.dest_ip='0.0.0.0/0'
set mwan3.default_rule.use_policy='operation_balance'
set mwan3.default_rule.family='ipv4'
set mwan3.default_rule.sticky='0'

# Gaming/VoIP: sticky ON to avoid IP changes, packet loss, jitter spikes.
set mwan3.gaming_udp=rule
set mwan3.gaming_udp.proto='udp'
set mwan3.gaming_udp.dest_port='3074,3478:3480,3659,500,4500,27000:27100'
set mwan3.gaming_udp.use_policy='low_latency_wan1'
set mwan3.gaming_udp.sticky='1'
set mwan3.gaming_udp.timeout='3600'

set mwan3.voip=rule
set mwan3.voip.proto='udp'
set mwan3.voip.dest_port='5060:5061,10000:20000'
set mwan3.voip.use_policy='low_latency_wan1'
set mwan3.voip.sticky='1'
set mwan3.voip.timeout='3600'

# HTTPS login-sensitive fallback: sticky to reduce auth/session breakage.
# Keep broad HTTPS non-sticky by default; add domain/ip-specific sticky rules via dashboard when needed.

commit mwan3
EOF

/etc/init.d/mwan3 enable
/etc/init.d/mwan3 restart
mwan3 status || true
