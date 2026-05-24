# 03 NIC Assignment

## Goal
Map physical ports to NexusGate roles (real deployed wiring).

## Assignment

- eth0 → LAN / management (admin MacBook direct); bridged with eth3 in `br-lan`
- eth1 → WAN1 Fiber (PPPoE) — TP-Link GPON ONT, Vivo Fibra
- eth2 → WAN2 Coax (DHCP) — cable modem in router mode (double-NAT v1)
- eth3 → LAN downlink to unmanaged 1Gb switch; bridged with eth0
- No wwan0 / 4G in v1

## Switch topology (eth3 → TP-Link 1Gb unmanaged)

| Switch port | Device | Role | Static/DHCP |
|---:|---|---|---|
| 1 | Home Wi-Fi router (TP-Link) | Wi-Fi AP for clients | DHCP → reserved .2 |
| 2 | CortexOS local VPS | Service host | DHCP → reserved .4 |
| 3 | WD NAS | Storage | DHCP → reserved .3 |

Home Wi-Fi router **must be in AP/Bridge mode** so Wi-Fi clients land directly on `192.168.100.0/24` and AdGuard sees every query. Router mode = double-NAT + AdGuard sees only router source IP.

## Actions

1. Identify ports using link LEDs and `ip link`.
2. Apply `configs/network-nics.uci` or run `scripts/configure-lan-eth3.sh` (bridges eth0+eth3).
3. Apply `configs/dhcp-lan.uci` (pool 50-249 + static reservations).
4. Connect admin PC to eth0 (or via switch on eth3).
5. Connect switch to eth3; fan out to home router, CortexOS, NAS.
6. Connect TP-Link GPON ONT to eth1.
7. Connect cable modem to eth2.
8. On each downstream device, set IPv4 = DHCP so reservation applies.

## Verification

- `br-lan` includes `eth0` and `eth3` (`uci show network.lan_dev.ports`).
- DHCP active on LAN; client receives 192.168.100.0/24 lease.
- LuCI reachable at `http://192.168.100.1`.
- `ip link` shows `eth0..eth3` UP.
- `cat /tmp/dhcp.leases` lists all reserved devices on their pinned IPs.
- From a Wi-Fi client: `dig @192.168.100.1 doubleclick.net +short` → `0.0.0.0` (AdGuard block).
