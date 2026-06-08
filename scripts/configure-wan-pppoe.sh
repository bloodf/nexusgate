#!/bin/sh
# Configure WAN1 on eth1 for Vivo Fibra via TP-Link GPON ONT.
# Detect ONT mode: bridge (router does PPPoE) vs router (ONT does PPPoE, gives private DHCP).
# Vivo PPPoE creds: cliente@cliente / cliente (generic; OLT auths via ONT serial).
set -eu

WAN_IF=${WAN_IF:-eth1}
PPP_USER=${PPP_USER:-cliente@cliente}
PPP_PASS=${PPP_PASS:-cliente}
METRIC=${METRIC:-10}

is_private_ip() {
  case "$1" in
    10.*|192.168.*|172.16.*|172.17.*|172.18.*|172.19.*|172.2[0-9].*|172.3[01].*|100.6[4-9].*|100.[7-9][0-9].*|100.1[01][0-9].*|100.12[0-7].*) return 0 ;;
    *) return 1 ;;
  esac
}

# Step 1: probe with DHCP to see if ONT is in router mode
uci set network.wan1=interface
uci set network.wan1.proto='dhcp'
uci set network.wan1.device="$WAN_IF"
uci set network.wan1.ipv6='0'
uci set network.wan1.defaultroute='0'
uci set network.wan1.metric="$METRIC"
uci commit network
/etc/init.d/network reload

ifup wan1 || true
sleep 8

IP=$(ifstatus wan1 2>/dev/null | jsonfilter -e '@["ipv4-address"][0].address' 2>/dev/null || echo "")

if [ -n "$IP" ] && is_private_ip "$IP"; then
  echo "ONT in router mode. wan1 got private IP $IP. Double-NAT (acceptable v1)."
  echo "Keeping wan1 proto=dhcp."
  exit 0
fi

echo "ONT appears in bridge mode (no DHCP lease). Switching wan1 to PPPoE."

uci set network.wan1.proto='pppoe'
uci set network.wan1.device="$WAN_IF"
uci set network.wan1.username="$PPP_USER"
uci set network.wan1.password="$PPP_PASS"
uci set network.wan1.ipv6='0'
uci set network.wan1.defaultroute='0'
# No VPS bonding -> MPTCP is pointless here. multipath='master'/'on' makes OMR
# thrash the PPPoE master (logread: "Set pppoe-wan1 to master ... deactivated ...
# off" looping), which contributed to the Vivo link flapping. Per-device affinity
# routes via single-nexthop tables (098-wan-affinity), not MPTCP, so turn it off.
uci set network.wan1.multipath='off'
# LCP echo keepalive: 4 missed echoes at 3s interval (~12s) declares the peer
# dead and tears the session down cleanly so omr-tracker/098 fail traffic over
# fast, instead of a half-open ppp lingering and black-holing packets.
uci set network.wan1.keepalive='4 3'
uci set network.wan1.metric="$METRIC"
uci commit network

# MSS clamp on the PPPoE egress. The stock fw4 mtu_fix rule clamps on the
# zone's ethernet devices (eth1/eth2), but Vivo egresses over pppoe-wan1
# (MTU ~1492). Without clamping the ppp device, full-size TCP segments black-hole
# (DNS/ICMP work, page loads stall) -- the classic PPPoE MSS symptom. Clamp both
# directions on any pppoe-* device, MSS = path MTU. fw4 includes this file into
# table inet fw4, so a forward-hook chain is valid here.
mkdir -p /etc/nftables.d
cat > /etc/nftables.d/21-pppoe-mss.nft <<'NFT'
# Managed by nexusgate configure-wan-pppoe.sh -- do not edit by hand.
chain pppoe_mss {
    type filter hook forward priority mangle; policy accept;
    oifname "pppoe-*" tcp flags syn tcp option maxseg size set rt mtu counter
    iifname "pppoe-*" tcp flags syn tcp option maxseg size set rt mtu counter
}
NFT
fw4 reload >/dev/null 2>&1 || true

/etc/init.d/network reload
ifup wan1
sleep 10

PUB=$(ifstatus wan1 2>/dev/null | jsonfilter -e '@["ipv4-address"][0].address' 2>/dev/null || echo "")
echo "wan1 PPPoE IP: ${PUB:-<none>}"
[ -n "$PUB" ] || { echo "PPPoE failed. Check creds (try cpf@vivo.com.br variant) or ONT mode."; exit 1; }
