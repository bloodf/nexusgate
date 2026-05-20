#!/bin/sh
set -eu

LAN_IP=${LAN_IP:-192.168.100.1}
LAN_NETMASK=${LAN_NETMASK:-255.255.255.0}
DHCP_START=${DHCP_START:-100}
DHCP_LIMIT=${DHCP_LIMIT:-150}
DHCP_LEASETIME=${DHCP_LEASETIME:-12h}

uci batch <<EOF
# Bridge eth2 + eth3 as LAN. eth3 is intended for home Wi-Fi router WAN/AP uplink.
set network.lan_dev=device
set network.lan_dev.name='br-lan'
set network.lan_dev.type='bridge'
delete network.lan_dev.ports 2>/dev/null || true
add_list network.lan_dev.ports='eth2'
add_list network.lan_dev.ports='eth3'

set network.lan=interface
set network.lan.device='br-lan'
set network.lan.proto='static'
set network.lan.ipaddr='$LAN_IP'
set network.lan.netmask='$LAN_NETMASK'

set dhcp.lan=dhcp
set dhcp.lan.interface='lan'
set dhcp.lan.start='$DHCP_START'
set dhcp.lan.limit='$DHCP_LIMIT'
set dhcp.lan.leasetime='$DHCP_LEASETIME'
set dhcp.lan.ignore='0'

commit network
commit dhcp
EOF

/etc/init.d/network reload
/etc/init.d/dnsmasq enable
/etc/init.d/dnsmasq restart

echo "LAN DHCP active on eth2+eth3 via br-lan at $LAN_IP"
echo "Connect home Wi-Fi router WAN/AP uplink to eth3. It will receive DHCP."
