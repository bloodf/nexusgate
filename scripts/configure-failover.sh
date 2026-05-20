#!/bin/sh
set -eu
opkg update; opkg install mwan3 luci-app-mwan3 umbim uqmi kmod-usb-net-qmi-wwan || true
uci batch <<'EOF'
set network.wan3=interface
set network.wan3.proto='qmi'
set network.wan3.device='/dev/cdc-wdm0'
set network.wan3.apn='internet'
set mwan3.wan3=interface
set mwan3.wan3.enabled='1'
set mwan3.wan3.family='ipv4'
set mwan3.wan3.reliability='1'
commit network
commit mwan3
EOF
/etc/init.d/network reload; /etc/init.d/mwan3 restart
