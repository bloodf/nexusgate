# Troubleshooting

Real issues hit during deployment, with fixes.

> **Routing model:** NexusGate now uses **per-device WAN affinity**
> (`scripts/configure-wan-affinity.sh`), not per-flow ECMP. Entries below that
> reference `ecmp-balance.sh` / `099-ecmp-balance` / table `991337` as the
> *active* policy are **legacy** — kept for history. ECMP table 991337 still
> exists (OMR core rebuilds it) but is shadowed by the affinity rules.

## Which WAN is a device on? / lock a device to WAN2 or WAN1

```sh
# What MACs are pinned where (live nft chain):
nft list chain inet fw4 wan_affinity

# Routing decision for a device by MAC's mark, or for default LAN:
ip route get 1.1.1.1 mark 0x10000          # WAN1-locked  -> table 100 / pppoe-wan1
ip route get 1.1.1.1 mark 0x20000          # WAN2-locked -> table 101 / eth2
ip route get 1.1.1.1 from 10.25.0.50 iif br-lan   # default LAN -> table 100

# Current device list (IP / MAC / hostname):
cat /tmp/dhcp.leases
```

Lock a device to WAN2 (or change which devices are WAN2-only):

```sh
# Re-run the installer with the full WAN2 MAC list (space-separated, lowercase):
WAN2_MACS="<mac:addr:1> <mac:addr:2> <mac:addr:3> <new:mac>" \
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
Fix: don't use mwan3. NexusGate uses per-device WAN affinity (kernel ip rules + nft marking) instead - applied by `scripts/configure-wan-affinity.sh`.

## Single LAN client always shows one WAN public IP

This is now **correct, expected behavior** under per-device affinity — each
device has one stable public IP. (Under the old ECMP model this was a symptom of
L3 hashing; it is no longer a problem.) Only investigate if the IP is the *wrong*
WAN for that device — see "Which WAN is a device on?" above.

## Table 991337 has only one nexthop (or empty) (historical)

> **Historical note.** Table `991337` was the ECMP load-balancer table used before per-device
> affinity. It is OMR-internal and still rebuilt by OMR core each tracker tick, but the
> affinity `pri 45 iif br-lan` rule permanently shadows it - LAN traffic never reaches it.
> Do NOT add a `pri 50 iif br-lan lookup 991337` rule and do NOT install `099-ecmp-balance`.
> Both are remnants of the retired ECMP model.

If you see a stale `pri 50 iif br-lan lookup 991337` rule (left over from a previous install):

```sh
ip rule del priority 50
```

Then verify the affinity rules are in place:

```sh
ip rule show | grep "iif br-lan"
# Expect: pri 45 iif br-lan lookup 100
```

If missing, re-run `098-wan-affinity` (see "ip rule pri 45 missing" above).

## ubus wan1/wan2 route arrays empty

```sh
ubus call network.interface.wan1 status
```
shows empty `route: []`.
Expected: OMR sets `defaultroute=0` on WANs. Don't use ubus for route discovery; read tables 6 (wan1) and 10 (wan2) directly.

## AdGuard not blocking ads

`dig @10.25.0.1 doubleclick.net +short` returns a real IP.
Cause: `/etc/adguardhome.yaml` has no `filters:` entries.
Fix: `scripts/configure-adguard-filters.sh` injects 4 AdGuard filter URLs (ids 1, 2, 11, 15) and restarts service.

## WAN1 (fiber/PPPoE) no IP

`ifstatus wan1` returns nothing on PPPoE.
Causes / fixes:

- ONT in router mode → wan1 should be `proto=dhcp`, not pppoe. Re-run `scripts/configure-wan-pppoe.sh`; it auto-detects.
- PPPoE credentials wrong → verify username/password with your ISP. (Reference deployment used generic `cliente@cliente`/`cliente` for Vivo Fibra — OLT authenticates by ONT serial, not credentials.)
- ONT not registered at OLT → contact your ISP to provision the ONT serial.

## WAN2 marked down / ~50% connections fail (omr-tracker ICMP block)

Symptoms: intermittent drops, `openmptcprouter.wan2.state=down`, table 10 shows
a stale or incorrect default route on `eth2`.

Cause: default omr-tracker pings 1.1.1.1 / 8.8.8.8. Some ISPs block ICMP upstream.
Tracker marks wan2 DOWN -> OMR installs broken down-state routes -> `098-wan-affinity`
reads the DOWN state and repoints WAN2-locked devices to WAN1 (failover), but WAN2 appears
permanently down to OMR even though the link is physically up.

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
curl --interface eth2 https://api.ipify.org   # WAN2 public IP
ip route show table 101               # WAN2 single nexthop (eth2) when up
```

## Third-party DNS / DoH upstream

AdGuard must use ISP plain DNS, not Cloudflare/Google/Quad9 DoH. Run
`scripts/configure-isp-dns.sh`. Resolvers are policy-routed: WAN1 DNS → table 6,
WAN2 DNS → table 10.


```sh
scripts/health-check.sh
```

Then run the `prompts/13-verification.md` checklist.
