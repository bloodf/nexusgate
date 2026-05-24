# Troubleshooting

Real issues hit during deployment, with fixes.

## mwan3 won't install

OMR is nftables-only; `luci-app-mwan3` depends on `iptables-mod-conntrack-extra` which is not in OMR repos.
Fix: don't use mwan3. Use kernel ECMP via OMR table 991337 (`scripts/configure-load-balancing.sh` + `scripts/ecmp-balance.sh` post-tracking hook).

## Single LAN client always shows one WAN public IP

LAN client to one server (e.g. `https://api.ipify.org`) returns same IP every time.
Cause: `net.ipv4.fib_multipath_hash_policy=0` (default L3 hash). `(srcIP,dstIP)` is constant → same bucket forever.
Fix:

```sh
sysctl -w net.ipv4.fib_multipath_hash_policy=1
echo 'net.ipv4.fib_multipath_hash_policy=1' > /etc/sysctl.d/99-ecmp.conf
```

## Table 991337 has only one nexthop (or empty)

```sh
ip route show table 991337
```

Cause: `099-ecmp-balance` post-tracking hook missing, not executable, or one of tables 6/10 has no default route.
Fix:

- Verify hook: `ls -l /usr/share/omr/post-tracking.d/099-ecmp-balance` (must be `+x`).
- Verify per-WAN tables: `ip route show table 6`, `ip route show table 10` — both need a default.
- If table empty, the WAN isn't really up (`ifstatus wan1`, check pppoe/dhcp lease).
- Run hook manually: `/usr/share/omr/post-tracking.d/099-ecmp-balance`.

## LAN traffic ignores 991337

`ip rule show | grep 991337` returns nothing.
Fix: `ip rule add priority 50 iif br-lan lookup 991337`. Persist in `/etc/rc.local`.

## ubus wan1/wan2 route arrays empty

```sh
ubus call network.interface.wan1 status
```
shows empty `route: []`.
Expected: OMR sets `defaultroute=0` on WANs. Don't use ubus for route discovery; read tables 6 (wan1) and 10 (wan2) directly.

## AdGuard not blocking ads

`dig @192.168.100.1 doubleclick.net +short` returns a real IP.
Cause: `/etc/adguardhome.yaml` has no `filters:` entries.
Fix: `scripts/configure-adguard-filters.sh` injects 4 AdGuard filter URLs (ids 1, 2, 11, 15) and restarts service.

## Fiber WAN no IP

`ifstatus wan1` returns nothing on PPPoE.
Causes / fixes:

- ONT in router mode → wan1 should be `proto=dhcp`, not pppoe. Re-run `scripts/configure-wan-pppoe.sh`; it auto-detects.
- PPPoE creds wrong → try `cpf@vivo.com.br` variant. Generic `cliente@cliente`/`cliente` works in most Vivo OLT regions because the OLT authenticates by ONT serial.
- ONT not registered at OLT → call Vivo to provision the ONT serial.

## Generic checks

```sh
scripts/health-check.sh
```

Then run the `prompts/13-verification.md` checklist.
