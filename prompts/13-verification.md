# 13 Verification

## Goal
Confirm ECMP load balancing, AdGuard DNS filtering, and WAN failover on real deployed router.

## Inputs
- Router IP: `192.168.100.1`
- WAN roles: eth1=wan1 (Fiber PPPoE), eth2=wan2 (Coax DHCP)
- LAN: eth0+eth3 bridged → br-lan

## Actions / Verification

### ECMP routing

```sh
ip route show table 991337
```
Expect two nexthops (via wan1 gateway and via wan2 gateway).

```sh
ip rule show | grep 991337
```
Expect `iif br-lan lookup 991337` (priority 50 or similar).

```sh
sysctl net.ipv4.fib_multipath_hash_policy
```
Expect `= 1` (L4 hash; src+dst port included).

### LAN-side fan-out (from a LAN client, not the router)

```sh
for i in $(seq 1 20); do curl -s https://api.ipify.org; echo; done
```
Expect **two distinct public IPs** alternating across the 20 requests (one per WAN). If only one IP appears, recheck `fib_multipath_hash_policy=1` and the `iif br-lan lookup 991337` rule.

### DNS filtering

```sh
dig @192.168.100.1 doubleclick.net +short
```
Expect `0.0.0.0` or NXDOMAIN.

```sh
dig @192.168.100.1 example.com +short
```
Expect a real IP.

If both return real IPs, AdGuard has no filter lists loaded. Run `scripts/configure-adguard-filters.sh`.

### WAN failover

1. Unplug eth1 (or eth2). Observe ipify loop now returns only the surviving WAN's IP.
2. Re-plug. After post-tracking hook re-runs (a few seconds), both IPs appear again.

### Health

```sh
scripts/health-check.sh
```

## Rollback
Restore `/etc/config/*` backups; reboot.
