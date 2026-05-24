# 03 NIC Assignment

## Goal
Map physical ports to NexusGate roles (real deployed wiring).

## Assignment

- eth0 → LAN / management (admin MacBook); bridged with eth3 in `br-lan`
- eth1 → WAN1 Vivo Fibra (PPPoE) — TP-Link GPON ONT
- eth2 → WAN2 Claro Coaxial (DHCP) — cable modem in router mode (double-NAT, modem can't bridge)
- eth3 → LAN downlink to TP-Link 1Gb unmanaged switch; bridged with eth0
- No wwan0 / 4G in v1

## Switch topology (eth3 → unmanaged switch)

| Switch port | Device | Notes |
|---:|---|---|
| 1 | TP-Link Deco BE65 main | AP mode; mesh of 5 Decos joins NexusGate LAN flat |
| 2 | CortexOS local VPS | DHCP, reserved to `192.168.100.10` |
| 3 | WD NAS | Firmware-configured static `192.168.100.187` |

Deco mesh is in **AP mode**: NexusGate is sole gateway/DHCP/DNS for all Wi-Fi clients. Decos themselves take dynamic leases (not reserved by design — mesh handles its own membership).

## Actions

1. Identify ports using link LEDs and `ip link`.
2. Apply `configs/network-nics.uci` or run `scripts/configure-lan-eth3.sh` (bridges eth0+eth3).
3. Apply `configs/dhcp-lan.uci` (pool 50-249, DNS push, CortexOS reservation).
4. Apply `scripts/configure-sqm.sh` (CAKE on both WANs at 95% of plan).
5. Apply `scripts/configure-dns-intercept.sh` (Tailscale-leftover DNS catch-all).
6. Connect admin PC to eth0 (or via switch on eth3).
7. Connect switch to eth3; fan out to Deco main, CortexOS, NAS.
8. Connect TP-Link GPON ONT to eth1.
9. Connect Claro cable modem to eth2.
10. On Deco app: **More → Advanced → Operating Mode → Access Point**.

## Verification

- `br-lan` includes `eth0` and `eth3`.
- DHCP active on LAN; clients receive `192.168.100.50-249` leases.
- All 5 Decos appear in `/tmp/dhcp.leases` (MAC prefix `bc:07:1d`).
- CortexOS lands on `192.168.100.10` (resolvable as `cortexos.lan`).
- `tc qdisc show | grep cake` lists 4 cake qdiscs (ingress+egress per WAN).
- From a Wi-Fi client: `dig @192.168.100.1 doubleclick.net +short` → `0.0.0.0`.
- Bufferbloat test from any Wi-Fi client → A or A+ under load.
