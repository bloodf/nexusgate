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
uci set network.wan1.multipath='on'
uci set network.wan1.metric="$METRIC"
uci commit network

/etc/init.d/network reload
ifup wan1
sleep 10

PUB=$(ifstatus wan1 2>/dev/null | jsonfilter -e '@["ipv4-address"][0].address' 2>/dev/null || echo "")
echo "wan1 PPPoE IP: ${PUB:-<none>}"
[ -n "$PUB" ] || { echo "PPPoE failed. Check creds (try cpf@vivo.com.br variant) or ONT mode."; exit 1; }
