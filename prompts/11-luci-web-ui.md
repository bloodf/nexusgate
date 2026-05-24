# 11 LuCI Web UI

## Goal
Install and verify OpenMPTCProuter/OpenWrt LuCI addons.

## Actions

1. Run `scripts/install-luci-addons.sh`.
2. Open `http://192.168.100.1`.
3. Confirm SQM, statistics, and vnstat pages are visible (mwan3 not installed; replaced by kernel ECMP).
4. Confirm OMR pages remain available when using OpenMPTCProuter.

## Verification

- LuCI HTTP/HTTPS reachable.
- `ip route show table 991337` shows two nexthops.
- SQM UI visible.
- Traffic graphs visible.
