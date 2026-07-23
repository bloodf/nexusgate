#!/bin/sh
set -eu

opkg update

# Required packages — hard-fail if any of these can't install.
opkg install \
  luci \
  luci-ssl \
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
  luci-app-commands

# Optional: OMR-specific bypass UI; absent on some OMR builds. Failure tolerated.
opkg install luci-app-omr-bypass || echo "NOTE: luci-app-omr-bypass unavailable (optional, continuing)"

/etc/init.d/uhttpd enable
/etc/init.d/uhttpd restart
/etc/init.d/collectd enable
/etc/init.d/collectd restart || true
/etc/init.d/vnstat enable
/etc/init.d/vnstat restart || true

echo "LuCI addons installed. Access: http://10.25.0.1 or https://10.25.0.1"
