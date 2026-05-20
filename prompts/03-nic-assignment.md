# 03 NIC Assignment

## Goal
Map physical ports to NexusGate roles.

## Assignment

- eth0 → WAN1 ISP #1
- eth1 → WAN2 ISP #2
- eth2 → LAN/admin
- eth3 → LAN-DHCP/home Wi-Fi router uplink
- wwan0 → 4G/LTE backup

## Actions

1. Identify ports using link LEDs and `ip link`.
2. Apply `configs/network-nics.uci` or run `scripts/configure-lan-eth3.sh`.
3. Connect home Wi-Fi router WAN/AP uplink to eth3.
4. Confirm router/client receives DHCP from `192.168.100.1/24`.

## Verification

- `br-lan` includes eth2 and eth3.
- DHCP active on LAN.
- LuCI reachable at `http://192.168.100.1`.
