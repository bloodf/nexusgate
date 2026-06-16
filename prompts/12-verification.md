# 12 Verification

## Goal
Confirm per-device WAN affinity routing, AdGuard DNS filtering, and WAN failover on a deployed router.

## Inputs
- Router IP: `10.25.0.1`
- WAN roles: eth1=wan1 (primary, PPPoE/fiber), eth2=wan2 (secondary, DHCP/cable)
- LAN: eth0+eth3 bridged -> br-lan

## Actions / Verification

### Affinity routing tables

```sh
ip rule show | grep -E "lookup (100|101)|iif br-lan"
```
Expect: pri-40 fwmark rule -> table 100 (WAN1), pri-41 fwmark rule -> table 101 (WAN2),
and pri-45 `iif br-lan lookup 100` (default egress for unmarked LAN traffic).

```sh
ip route show table 100
ip route show table 101
```
Expect: each table has exactly ONE default nexthop (one gateway, one WAN). No multipath entries.

### OMR multipath disabled

```sh
uci -q get openmptcprouter.settings.master
```
Expect: any value other than `balancing` (e.g. `master` or empty).

```sh
uci -q get network.wan1.multipath
uci -q get network.wan2.multipath
```
Expect: both return `off`.

### LAN-side stability check (run from a LAN client, NOT the router)

Default device (no Claro lock - egresses via WAN1):
```sh
for i in $(seq 1 10); do curl -s https://api.ipify.org; echo; done
```
Expect: the SAME WAN1 public IP on every request. A stable single IP confirms per-device affinity is working.

Claro-locked device (MAC in Claro lock list - egresses via WAN2):
```sh
for i in $(seq 1 10); do curl -s https://api.ipify.org; echo; done
```
Expect: the SAME WAN2 public IP on every request.

If IPs alternate across requests, the affinity mark is not being applied; verify `nft list ruleset | grep mark` and check that `098-wan-affinity` hook ran.

### DNS filtering

```sh
dig @10.25.0.1 doubleclick.net +short
```
Expect `0.0.0.0` or NXDOMAIN.

```sh
dig @10.25.0.1 example.com +short
```
Expect a real IP.

If both return real IPs, AdGuard has no filter lists loaded. Run `scripts/configure-adguard-filters.sh`.

### WAN failover

1. Unplug eth1 (WAN1). Observe that the ipify loop on a default device now shows the WAN2 IP (one stable IP - the surviving WAN).
2. Re-plug eth1. After the tracker tick runs, the default device shifts back to the WAN1 IP.
3. Repeat with eth2 (WAN2): Claro-locked devices shift to WAN1, then back after re-plug.

At no point should two distinct IPs alternate within a single device's request loop.

### Health

```sh
scripts/health-check.sh
```

## Rollback
Restore `/etc/config/*` backups; reboot.
