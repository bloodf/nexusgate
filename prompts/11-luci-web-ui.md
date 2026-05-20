# 11 LuCI Web UI

## Goal
Install and verify OpenMPTCProuter/OpenWrt LuCI addons.

## Actions

1. Run `scripts/install-luci-addons.sh`.
2. Open `http://192.168.100.1`.
3. Confirm mwan3, SQM, statistics, and vnstat pages are visible.
4. Confirm OMR pages remain available when using OpenMPTCProuter.

## Verification

- LuCI HTTP/HTTPS reachable.
- `mwan3 status` visible.
- SQM UI visible.
- Traffic graphs visible.
