#!/bin/sh
set -eu

# Wiring: eth0 = LAN/management (admin PC), eth3 = LAN downlink to home Wi-Fi router.
# Both bridged into br-lan.
# DHCP is owned solely by configs/dhcp-lan.uci (the single source of truth: /16 pool
# starting at 10.25.1.1, ~4096 leases, DNS push, CortexOS reservation); this script sets
# up only the eth0+eth3 LAN bridge.

LAN_IP=${LAN_IP:-10.25.0.1}
LAN_NETMASK=${LAN_NETMASK:-255.255.0.0}

uci batch <<EOF
# Bridge eth0 + eth3 as LAN. eth3 is the home Wi-Fi router uplink.
# Section name MUST match configs/network-nics.uci ('br_lan'); using a
# different named section (old 'lan_dev') plus a uci import of network-nics.uci
# yields TWO device sections both claiming name 'br-lan'. Migrate/clean up.
delete network.lan_dev
set network.br_lan=device
set network.br_lan.name='br-lan'
set network.br_lan.type='bridge'
delete network.br_lan.ports
add_list network.br_lan.ports='eth0'
add_list network.br_lan.ports='eth3'

set network.lan=interface
set network.lan.device='br-lan'
set network.lan.proto='static'
set network.lan.ipaddr='$LAN_IP'
set network.lan.netmask='$LAN_NETMASK'

commit network
EOF

/etc/init.d/network reload
/etc/init.d/dnsmasq enable
/etc/init.d/dnsmasq restart

echo "LAN bridge configured: eth0+eth3 via br-lan at $LAN_IP"
echo "Apply DHCP pool separately: uci import -m dhcp < configs/dhcp-lan.uci && uci commit dhcp && /etc/init.d/dnsmasq restart"
echo "Connect home Wi-Fi router WAN/AP uplink to eth3. It will receive DHCP."
