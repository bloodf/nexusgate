# 09 LuCI Web UI

## Goal
Install and verify OpenMPTCProuter/OpenWrt LuCI addons.

## Actions

1. Run `scripts/install-luci-addons.sh`.
2. Open `http://192.168.100.1`.
3. Confirm SQM, statistics, and vnstat pages are visible (no multi-WAN LuCI app required; multi-WAN is handled by per-device WAN affinity, not a LuCI multi-WAN app).
4. Confirm OMR pages remain available when using OpenMPTCProuter.
5. Confirm WAN affinity web UI is reachable at `http://192.168.100.1/cgi-bin/wan-affinity`.

## Verification

- LuCI HTTP/HTTPS reachable.
- SQM UI visible.
- Traffic graphs visible.
- WAN affinity UI reachable at `http://192.168.100.1/cgi-bin/wan-affinity`.
