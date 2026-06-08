# NexusGate edge cutover runbook

Moving the edge from your previous router to NexusGate (OpenMPTCProuter), dual-WAN, no VPS
bonding. WAN1 (primary) as default, WAN2 (secondary/fallback) + per-device lock list. This
file is the pre-cutover audit result and the access-safe switch sequence.

> **Reference deployment:** The original cutover was from a TP-Link ER605 with
> WAN1 = Vivo Fibra (PPPoE) and WAN2 = Claro Coaxial (DHCP). Replace these with
> your own ISPs, connection types, and credentials. See
> [Reference deployment in README](../README.md#reference-deployment).

## Interface / cabling map

| Port | Role | Notes |
|------|------|-------|
| eth0 | LAN (br-lan) | switch or Wi-Fi AP |
| eth1 | WAN1 (primary) | PPPoE or DHCP, `pppoe-wan1` or `wan1`, table 6, OMR wan1 |
| eth2 | WAN2 (secondary) | DHCP, table 10, OMR wan2. **SSH lifeline during cutover** |
| eth3 | LAN (br-lan) | switch or Wi-Fi AP |

`br-lan = eth0 + eth3`. Both are LAN ports - switch and Wi-Fi AP may use either; the
bridge absorbs both. eth1/eth2 are isolated WANs, never in the bridge.

WAN2 stays router-mode (double-NAT) if the modem cannot bridge. Acceptable: every WAN2
device still egresses one stable public IP (the modem WAN IP); users never see it.

## Routing model

- LAN traffic uses tables 100/101, governed by `098-wan-affinity` each tracker tick.
  - mark `0x10000` -> ip rule pri 40 -> table 100 (WAN1 primary, WAN2 failover)
  - mark `0x20000` -> ip rule pri 41 -> table 101 (WAN2 primary, WAN1 failover)
  - unmarked LAN -> pri 45 `iif br-lan` -> table 100 (WAN1 default), shadows OMR
    core pri 50 ECMP (table 991337)
- Single-nexthop tables = no L4 hash = stable per-device egress IP (the fix for
  the streaming/gaming breakage the ECMP load-balancer caused).
- Router-origin traffic (Tailscale/SSH/DNS/AdGuard) rides the MAIN table default,
  rebuilt every tick by OMR `003-up` from live WAN state - NOT governed by 098.
  SSH survival depends on this main-default failover.

## Pre-cutover audit (server "cannot break" verdict)

All items verified GREEN and reboot-safe before cabling WAN1:

- wan1 (primary): `proto=pppoe device=eth1 multipath=off keepalive='4 3' ip4table=6
  defaultroute=0 metric=6 ipv6=0`. multipath off because no VPS -> MPTCP master
  only thrashes the PPPoE link.
- wan2 (secondary): `proto=dhcp device=eth2 ip4table=10 metric=10`. Left `multipath=on`
  deliberately - it is the live SSH lifeline and runs stable; not touched pre-cutover.
- br-lan = eth0 + eth3; eth1/eth2 isolated as WANs.
- firewall zone_wan masq=1 mtu_fix=1 network=`wan1 wan2 wan1_6 wan2_6`; zone_lan
  mtu_fix=1.
- SQM CAKE: pppoe-wan1 at WAN1 plan rates, eth2 at WAN2 plan rates (see [NETWORKING.md](NETWORKING.md#sqm--cake)).
- **omr-tracker probes BOTH wan1 and wan2 via the `defaults` stanza (type=ping,
  world host set).** There is no per-wan stanza, so both inherit active ping
  probing - router-origin failover is symmetric in both directions. (Correction to
  an earlier assumption that wan2 used type=none and was unprobed - it does not.)
- `098-wan-affinity` is the egress-verified version: liveness is `ping -I <dev>`
  (SO_BINDTODEVICE), authoritative over stale uci state in both directions.
- MSS clamp `/etc/nftables.d/21-pppoe-mss.nft` staged; loads on fw4 reload once
  pppoe-wan1 exists.
- `/etc/nftables.d/20-wan-affinity.nft` loaded, chain empty (both lock lists empty)
  = safe default: every device -> WAN1. Reboot-safe (fw4 loads the static file).
- rc.local clean: only the 4 DNS policy rules (pri 89-92, one unique priority per
  ISP resolver IP); zero ECMP / 991337 / 099 residue.
- AdGuard upstreams = ISP resolvers, each policy-routed out its own WAN.
- `openmptcprouter.settings.defaultgw` empty = treated as not-0 -> main default
  WILL be set on boot.

### Cable-gated unknowns (cannot prove without eth1 -> WAN1 modem/ONT)

These are physics, not config gaps - verify live after `ifup wan1`:

- A. pppoe-wan1 (or wan1 DHCP) comes up and gets a public IP.
- B. pppoe-wan1 gets masqueraded (live srcnat shows `oifname { eth1, eth2 }` only
  because pppoe-wan1 does not exist yet; fw4 should add it from the wan1 logical
  zone membership - confirm `nft list chain inet fw4 srcnat_wan`).
- C. MSS clamp chain loads.
- D. per-device stable egress IP + failover (needs WAN1 + Wi-Fi AP + real clients).

## Cutover sequence (access-safe)

WAN2/eth2 stays plugged as the SSH lifeline throughout. Previous router = physical rollback.

1. Operator cables: eth1 -> WAN1 modem/ONT, Wi-Fi AP -> a LAN port (eth0/eth3). Leave WAN2.
2. Arm watchdog (30-min blackout guard, restores WAN2 default if box goes dark):
   `setsid sh /root/cutover-watchdog.sh &`
3. `ifup wan1` (targeted - avoids two global `network reload`s).
4. Verify A-C: pppoe-wan1 public IP, srcnat covers pppoe-wan1, MSS chain loaded,
   main default reconverged via 003-up.
5. One tracker tick -> verify per-device egress IP stable (`curl ifconfig.me` x5
   from a LAN client = same WAN1 IP every time).
6. Failover test both directions (`ifdown wan1` -> LAN + SSH hold on WAN2;
   `ifup wan1` -> shift back).
7. Disarm watchdog (`pkill -f cutover-watchdog.sh`).
8. Post-stable: populate the WAN2 MAC lock list via the web UI (rewrites the
   persistent 20-wan-affinity.nft -> reboot-safe). Never guess a MAC.

## Rollback

Move WAN1 modem/ONT + Wi-Fi AP back to the previous router. NexusGate keeps WAN2
and stays reachable via Tailscale. No router config rollback needed - the affinity
chain is empty (all -> WAN1) and harmless when WAN1 is absent.
