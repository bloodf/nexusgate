# 03 NIC Assignment

## Goal
Map physical ports to NexusGate roles (real deployed wiring).

## Assignment

- eth0 → LAN / management (admin PC); bridged with eth3 in `br-lan`
- eth1 → WAN1 Fiber (PPPoE) — TP-Link GPON ONT, Vivo Fibra
- eth2 → WAN2 Coax (DHCP) — cable modem in router mode (double-NAT v1)
- eth3 → LAN downlink to home Wi-Fi router; bridged with eth0
- No wwan0 / 4G in v1

## Actions

1. Identify ports using link LEDs and `ip link`.
2. Apply `configs/network-nics.uci` or run `scripts/configure-lan-eth3.sh` (bridges eth0+eth3).
3. Connect admin PC to eth0 (or via the home router on eth3).
4. Connect home Wi-Fi router WAN/AP uplink to eth3.
5. Connect TP-Link GPON ONT to eth1.
6. Connect cable modem to eth2.

## Verification

- `br-lan` includes `eth0` and `eth3` (`uci show network.lan_dev.ports`).
- DHCP active on LAN; client receives 192.168.100.0/24 lease.
- LuCI reachable at `http://192.168.100.1`.
- `ip link` shows `eth0..eth3` UP.
