# Web UI

NexusGate uses built-in OpenMPTCProuter/OpenWrt LuCI instead of a custom dashboard.

## Access

```text
http://192.168.100.1
https://192.168.100.1
ssh root@192.168.100.1
```

## Installed addons

Run:

```sh
scripts/install-luci-addons.sh
```

Adds:

- `luci-app-mwan3`
- `luci-app-sqm`
- `luci-app-statistics`
- `luci-app-vnstat`
- `luci-app-firewall`
- `luci-app-commands`
- 4G modem LuCI protocols
- OMR bypass UI when available

## Why no custom dashboard

- Less attack surface
- No Docker
- No Node runtime
- Native OpenWrt config writes
- Works offline
