# 04 WAN Config

## Goal
Bring up WAN1 (Fiber PPPoE) and WAN2 (Coax DHCP) on real deployed wiring.

## Inputs
- Router IP: `192.168.100.1`
- WAN roles: eth1 → wan1 (Vivo Fibra PPPoE), eth2 → wan2 (Coax DHCP)
- LAN: eth0 + eth3 bridged → `br-lan`
- Vivo PPPoE creds (generic, OLT auths via ONT serial): user `cliente@cliente`, pass `cliente`. Fallback: `cpf@vivo.com.br` variant.

## GPON ONT mode detection

TP-Link GPON ONT can be in:

- **Bridge mode**: router does PPPoE on eth1; gets public IP on `pppoe-wan1`.
- **Router mode**: ONT does PPPoE itself; hands eth1 a private DHCP lease (10.x.x.x or 192.168.x.x). Double-NAT but works.

Detection:

```sh
uci set network.wan1.proto=dhcp; uci commit network
ifup wan1
sleep 8
ifstatus wan1 | jsonfilter -e '@["ipv4-address"][0].address'
```

If private IP returned → router mode, keep DHCP. If empty → bridge mode, switch to PPPoE.

## Actions

1. Back up `/etc/config/network`.
2. Run `scripts/configure-wan-pppoe.sh` (auto-detects bridge vs router mode).
3. Bring up wan2 (Coax DHCP): `uci set network.wan2.proto=dhcp; uci set network.wan2.device=eth2; uci set network.wan2.defaultroute=0; uci set network.wan2.metric=20; uci commit; ifup wan2`.
4. Confirm both WANs have IPs via `ifstatus wan1` and `ifstatus wan2`.

## Verification

- `ifstatus wan1` → public IP (bridge mode) OR private IP (router mode, double-NAT).
- `ifstatus wan2` → DHCP IP from cable modem.
- `ping -I pppoe-wan1 1.1.1.1` and `ping -I eth2 1.1.1.1` both succeed.
- Tables 6 and 10 each have a default route: `ip route show table 6`, `ip route show table 10`.

## Rollback
Restore `/etc/config/network` backup; `/etc/init.d/network restart`.
