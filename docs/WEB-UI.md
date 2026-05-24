# Web UI

NexusGate uses the native OpenMPTCProuter/OpenWrt LuCI web interface.

## Access

```text
http://192.168.100.1
https://192.168.100.1
ssh root@192.168.100.1
```

## Install UI addons

```sh
scripts/install-luci-addons.sh
```

## Included LuCI modules

- `luci-app-sqm` for CAKE/SQM configuration
- `luci-app-statistics` for collectd graphs
- `luci-app-vnstat` for bandwidth accounting
- `luci-app-firewall` for firewall management
- `luci-app-commands` for operator diagnostics
- `luci-app-omr-bypass` when available

mwan3 not installed (depends on `iptables-mod-conntrack-extra`, missing on OMR nftables-only system). Multi-WAN handled by kernel ECMP in OMR table 991337.

## Operator workflow

1. Connect to LAN through `eth0` directly, or via home Wi-Fi router on `eth3`.
2. Open LuCI at `http://192.168.100.1`.
3. Verify WAN health: `ip route show table 991337` (two nexthops), `ifstatus wan1`, `ifstatus wan2`.
4. Verify SQM queues in SQM.
5. Verify bandwidth graphs in statistics/vnstat.
