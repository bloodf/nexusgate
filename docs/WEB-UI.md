# Web UI

NexusGate uses the native OpenMPTCProuter/OpenWrt LuCI web interface.

## Access

```text
http://192.168.100.1
https://192.168.100.1
ssh root@192.168.100.1
```

## Install UI addons

Run:

```sh
scripts/install-luci-addons.sh
```

## Included LuCI modules

- `luci-app-mwan3` for multi-WAN policy routing and failover
- `luci-app-sqm` for CAKE/SQM configuration
- `luci-app-statistics` for collectd graphs
- `luci-app-vnstat` for bandwidth accounting
- `luci-app-firewall` for firewall management
- `luci-app-commands` for operator diagnostics
- `luci-proto-qmi`, `luci-proto-mbim`, `luci-proto-modemmanager` for 4G/LTE modems
- `luci-app-omr-bypass` when available

## Operator workflow

1. Connect to LAN through `eth2` or `eth3`.
2. Open LuCI at `http://192.168.100.1`.
3. Verify WAN health in mwan3.
4. Verify SQM queues in SQM.
5. Verify bandwidth graphs in statistics/vnstat.
