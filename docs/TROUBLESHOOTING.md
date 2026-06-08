# Troubleshooting

Real issues hit during deployment, with fixes.

> **Routing model:** NexusGate now uses **per-device WAN affinity**
> (`scripts/configure-wan-affinity.sh`), not per-flow ECMP. Entries below that
> reference `ecmp-balance.sh` / `099-ecmp-balance` / table `991337` as the
> *active* policy are **legacy** — kept for history. ECMP table 991337 still
> exists (OMR core rebuilds it) but is shadowed by the affinity rules.

## Which WAN is a device on? / lock a device to Claro or Vivo

```sh
# What MACs are pinned where (live nft chain):
nft list chain inet fw4 wan_affinity

# Routing decision for a device by MAC's mark, or for default LAN:
ip route get 1.1.1.1 mark 0x10000          # Vivo-locked  -> table 100 / pppoe-wan1
ip route get 1.1.1.1 mark 0x20000          # Claro-locked -> table 101 / eth2
ip route get 1.1.1.1 from 192.168.100.50 iif br-lan   # default LAN -> table 100

# Current device list (IP / MAC / hostname):
cat /tmp/dhcp.leases
```

Lock a device to Claro (or change which devices are Claro-only):

```sh
# Re-run the installer with the full Claro MAC list (space-separated, lowercase):
CLARO_MACS="40:f6:bc:38:df:7c 44:d5:cc:e5:ad:a7 1c:fe:2b:f3:84:fc a8:a0:92:2f:9a:dc <new:mac>" \
  sh /root/configure-wan-affinity.sh
```

This regenerates `/etc/nftables.d/20-wan-affinity.nft`, runs `fw4 reload`, and
re-applies `098-wan-affinity` — effective immediately. The device must reconnect
(or its conntrack entries age out) for in-flight sessions to move; new
connections use the new WAN at once. The device-management WebUI does the same
edit-and-apply on save.

## Device still on the wrong WAN after locking it

- Confirm the MAC is in the live chain: `nft list chain inet fw4 wan_affinity`.
  If absent, the installer rejected it (invalid MAC format) — check casing /
  colons; it must be `aa:bb:cc:dd:ee:ff`.
- The marking is by **client MAC**, so it only works for devices on the L2 LAN
  (Deco APs are in AP mode, so Wi-Fi client MACs are visible — good). A device
  behind a downstream NAT/router would present that router's MAC, not its own.
- Existing sessions keep their old egress until conntrack ages out. Verify with
  `conntrack -L | grep <device-ip>` and reconnect the device to force-new flows.

## ip rule pri 45 (LAN default) missing or after pri 50

```sh
ip rule show | grep "iif br-lan"
```

Expect `45: ... iif br-lan lookup 100` **before** `50: ... iif br-lan lookup
991337`. If pri 45 is missing, OMR's pri-50 ECMP rule wins and devices flap
across WANs again.
Fix: run `/usr/share/omr/post-tracking.d/098-wan-affinity` (re-adds pri 45 and
removes any legacy pri-50 → 100 rule). It re-asserts every omr-tracker tick.

## mwan3 won't install

OMR is nftables-only; `luci-app-mwan3` depends on `iptables-mod-conntrack-extra` which is not in OMR repos.
Fix: don't use mwan3. Use kernel ECMP via OMR table 991337 (`scripts/configure-load-balancing.sh` + `scripts/ecmp-balance.sh` post-tracking hook).

## Single LAN client always shows one WAN public IP

This is now **correct, expected behavior** under per-device affinity — each
device has one stable public IP. (Under the old ECMP model this was a symptom of
L3 hashing; it is no longer a problem.) Only investigate if the IP is the *wrong*
WAN for that device — see "Which WAN is a device on?" above.

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

## Claro WAN marked down / ~50% connections fail (ECMP + ICMP block)

Symptoms: intermittent drops, `openmptcprouter.wan2.state=down`, table 14 shows
`default via 200.204.204.206 dev eth2` (Vivo gateway on wrong interface).

Cause: default omr-tracker pings 1.1.1.1 / 8.8.8.8. Claro blocks ICMP upstream.
Tracker marks wan2 DOWN → OMR installs broken down-state routes → ECMP still
hashes ~50% of flows to dead path.

Fix:

```sh
scripts/configure-omr-tracker.sh   # wan1=ISP DNS check, wan2=type none
scripts/configure-isp-dns.sh       # AdGuard -> ISP resolvers + policy routes
sh scripts/configure-wan-affinity.sh  # re-applies affinity (098 respects OMR state)
/etc/init.d/omr-tracker restart
```

Verify:

```sh
uci get openmptcprouter.wan2.state    # expect up
curl --interface eth2 https://api.ipify.org   # Claro public IP
ip route show table 101               # Claro single nexthop (eth2) when up
```

## Third-party DNS / DoH upstream

AdGuard must use ISP plain DNS, not Cloudflare/Google/Quad9 DoH. Run
`scripts/configure-isp-dns.sh`. Resolvers are policy-routed: Vivo DNS → table 6,
Claro DNS → table 10.


```sh
scripts/health-check.sh
```

Then run the `prompts/13-verification.md` checklist.
