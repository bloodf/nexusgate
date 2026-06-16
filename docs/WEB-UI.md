# Web UI

NexusGate uses the native OpenMPTCProuter/OpenWrt LuCI web interface.

## Access

```text
http://10.25.0.1
https://10.25.0.1
ssh root@10.25.0.1
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

mwan3 not installed (depends on `iptables-mod-conntrack-extra`, missing on OMR nftables-only system). Multi-WAN handled by per-device WAN affinity (nft MAC marking + single-nexthop tables 100/101 + `098-wan-affinity` hook).

## Operator workflow

1. Connect to LAN through `eth0` directly, or via home Wi-Fi router on `eth3`.
2. Open LuCI at `http://10.25.0.1`.
3. Verify WAN health: `ip route show table 100`, `ip route show table 101`, `ifstatus wan1`, `ifstatus wan2`.
4. Verify SQM queues in SQM.
5. Verify bandwidth graphs in statistics/vnstat.
6. Manage per-device WAN assignments at `http://10.25.0.1/cgi-bin/wan-affinity`.
