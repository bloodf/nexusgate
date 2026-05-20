#!/bin/sh
set -eu

opkg update
opkg install \
  luci \
  luci-ssl \
  luci-app-mwan3 \
  luci-app-sqm \
  luci-app-statistics \
  collectd \
  collectd-mod-interface \
  collectd-mod-ping \
  collectd-mod-cpu \
  collectd-mod-memory \
  luci-app-vnstat \
  vnstat \
  luci-app-firewall \
  luci-app-commands \
  luci-proto-qmi \
  luci-proto-mbim \
  luci-proto-modemmanager \
  luci-app-omr-bypass || true

/etc/init.d/uhttpd enable
/etc/init.d/uhttpd restart
/etc/init.d/collectd enable
/etc/init.d/collectd restart || true
/etc/init.d/vnstat enable
/etc/init.d/vnstat restart || true

echo "LuCI addons installed. Access: http://192.168.100.1 or https://192.168.100.1"
