# 04 WAN Config

## Goal
Bring up WAN1 (primary, e.g. PPPoE/fiber) and WAN2 (secondary, e.g. DHCP/cable).

## Inputs
- Router IP: `10.25.0.1`
- WAN roles: eth1 → wan1 (primary PPPoE or DHCP), eth2 → wan2 (secondary DHCP)
- LAN: eth0 + eth3 bridged → `br-lan`
- WAN1 PPPoE credentials: `<pppoe-username>` / `<pppoe-password>` (obtain from your ISP; see [Reference deployment in README](../README.md#reference-deployment) for example values).

## GPON ONT / fiber modem mode detection

A GPON ONT or fiber modem can be in:

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
