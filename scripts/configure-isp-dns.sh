#!/bin/sh
# Point AdGuard Home upstream at ISP resolvers (plain DNS, no DoH/Cloudflare/Google)
# and policy-route each resolver out its own WAN table (6=wan1, 10=wan2).
#
# Chain stays: LAN -> dnsmasq :53 -> AdGuard 127.0.0.1:5354 -> ISP DNS
#
# Reads live DNS from wan1/wan2 leases when jsonfilter is available; falls back
# to Vivo/Claro defaults for this deployment.

set -eu

CFG=${CFG:-/etc/adguardhome.yaml}
WAN1_DNS1=${WAN1_DNS1:-187.50.250.115}
WAN1_DNS2=${WAN1_DNS2:-187.50.250.215}
WAN2_DNS1=${WAN2_DNS1:-181.213.132.2}
WAN2_DNS2=${WAN2_DNS2:-181.213.132.3}

if command -v jsonfilter >/dev/null 2>&1; then
	_live1=$(ifstatus wan1 2>/dev/null | jsonfilter -e '@["inactive"]["dns-server"][0]' 2>/dev/null || true)
	_live2=$(ifstatus wan1 2>/dev/null | jsonfilter -e '@["inactive"]["dns-server"][1]' 2>/dev/null || true)
	[ -n "$_live1" ] && WAN1_DNS1="$_live1"
	[ -n "$_live2" ] && WAN1_DNS2="$_live2"
	_live3=$(ifstatus wan2 2>/dev/null | jsonfilter -e '@["inactive"]["dns-server"][0]' 2>/dev/null || true)
	_live4=$(ifstatus wan2 2>/dev/null | jsonfilter -e '@["inactive"]["dns-server"][1]' 2>/dev/null || true)
	[ -n "$_live3" ] && WAN2_DNS1="$_live3"
	[ -n "$_live4" ] && WAN2_DNS2="$_live4"
fi

[ -f "$CFG" ] || { echo "AdGuard config not found: $CFG"; exit 1; }

BAK="${CFG}.bak.$(date +%s)"
cp "$CFG" "$BAK"
TMP=$(mktemp)

awk '
  BEGIN { skip_up=0; skip_bs=0 }
  /^  upstream_dns:/ {
    print
    print "    - '"$WAN1_DNS1"'"
    print "    - '"$WAN1_DNS2"'"
    print "    - '"$WAN2_DNS1"'"
    print "    - '"$WAN2_DNS2"'"
    skip_up=1; next
  }
  skip_up==1 && /^    - / { next }
  skip_up==1 && /^  upstream_dns_file:/ { skip_up=0; print; next }
  /^  bootstrap_dns:/ { print "  bootstrap_dns: []"; skip_bs=1; next }
  skip_bs==1 && /^    - / { next }
  skip_bs==1 && /^  fallback_dns:/ { skip_bs=0; print "  fallback_dns: []"; next }
  /^  upstream_mode:/ { print "  upstream_mode: parallel"; next }
  { print }
' "$CFG" > "$TMP"
mv "$TMP" "$CFG"
echo "AdGuard backup: $BAK"

/etc/init.d/adguardhome restart
sleep 3

# Policy-route ISP resolvers out matching WAN tables.
# One UNIQUE priority per upstream IP. iproute drops a rule added at an
# already-used priority, so the old same-priority loop form silently kept only
# one IP per WAN - the dropped resolver then leaked out the default WAN and
# timed out (Claro 181.213.132.2 over Vivo -> i/o timeout). Keep 4 distinct.
_isp_dns_policy() {
	_add() { ip rule show | grep -q "to $1 lookup $2" || ip rule add priority "$3" to "$1" lookup "$2"; }
	_add "$WAN1_DNS1" 6  89
	_add "$WAN1_DNS2" 6  90
	_add "$WAN2_DNS1" 10 91
	_add "$WAN2_DNS2" 10 92
}

_isp_dns_policy

# Persist across reboot (idempotent append).
RC=/etc/rc.local
MARK="# nexusgate-isp-dns-policy"
if ! grep -q "$MARK" "$RC" 2>/dev/null; then
	sed -i "/^exit 0/i $MARK" "$RC"
	sed -i "/^exit 0/i ip rule add priority 89 to $WAN1_DNS1 lookup 6 2>/dev/null" "$RC"
	sed -i "/^exit 0/i ip rule add priority 90 to $WAN1_DNS2 lookup 6 2>/dev/null" "$RC"
	sed -i "/^exit 0/i ip rule add priority 91 to $WAN2_DNS1 lookup 10 2>/dev/null" "$RC"
	sed -i "/^exit 0/i ip rule add priority 92 to $WAN2_DNS2 lookup 10 2>/dev/null" "$RC"
fi

echo
echo "== AdGuard upstream =="
grep -A6 "^  upstream_dns:" "$CFG"
echo
echo "== DNS policy rules =="
ip rule show | grep -E "$(echo "$WAN1_DNS1|$WAN1_DNS2|$WAN2_DNS1|$WAN2_DNS2" | tr '|' '\\|')" || true
echo
echo "Verify:"
dig @"${WAN1_DNS1}" google.com.br +time=3 +short | head -1 || true
dig @192.168.100.1 google.com.br +time=3 +short | head -1 || true
