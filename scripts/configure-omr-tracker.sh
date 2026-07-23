#!/bin/sh
# OMR tracker health checks tuned for Brazilian ISPs.
#
# Problem: default omr-tracker uses ICMP ping to 1.1.1.1 / 8.8.8.8. Claro (and
# some other ISPs) block ICMP to the public internet. Tracker marks wan2 DOWN,
# OMR installs broken "down" routes (table 14 with Vivo gateway on eth2), and
# ~50% of ECMP flows die even though HTTP/TCP through Claro works fine.
#
# Fix:
#   wan1 (Vivo): DNS check against Vivo resolvers (from PPPoE/DHCP lease).
#   wan2 (Claro): type=none — link/DHCP up is enough; ICMP is blocked upstream.
#     Optional: set WAN2_TRACKER_TYPE=httping and WAN2_HTTP_HOST for HTTP probe.
#
# Re-run after omr-tracker package upgrades (may reset /etc/config/omr-tracker).

set -eu

WAN1_DNS1=${WAN1_DNS1:-187.50.250.115}
WAN1_DNS2=${WAN1_DNS2:-187.50.250.215}
WAN2_TRACKER_TYPE=${WAN2_TRACKER_TYPE:-none}
# Only 'dns' and 'none' are verified against this omr-tracker deployment.
# Other types (e.g. httping) need schema-verified target options; reject
# them BEFORE any uci mutation so we never commit a broken tracker config.
case "$WAN2_TRACKER_TYPE" in
	dns|none) ;;
	*)
		echo "ERROR: unsupported WAN2_TRACKER_TYPE='$WAN2_TRACKER_TYPE' (allowed: dns, none)." >&2
		echo "  Verify the installed omr-tracker UCI schema before adding new types." >&2
		exit 1
		;;
esac
WAN2_DNS1=${WAN2_DNS1:-181.213.132.2}
WAN2_DNS2=${WAN2_DNS2:-181.213.132.3}

# Auto-read ISP DNS from live leases when available.
if command -v jsonfilter >/dev/null 2>&1; then
	# peerdns=0 -> ISP DNS reported under "inactive"; active path covers peerdns=1.
	# Try active path first, fall back to inactive.
	_w1=$(ifstatus wan1 2>/dev/null || true)
	_live1=$(echo "$_w1" | jsonfilter -e '@["dns-server"][0]' 2>/dev/null || true)
	[ -z "$_live1" ] && _live1=$(echo "$_w1" | jsonfilter -e '@["inactive"]["dns-server"][0]' 2>/dev/null || true)
	_live2=$(echo "$_w1" | jsonfilter -e '@["dns-server"][1]' 2>/dev/null || true)
	[ -z "$_live2" ] && _live2=$(echo "$_w1" | jsonfilter -e '@["inactive"]["dns-server"][1]' 2>/dev/null || true)
	[ -n "$_live1" ] && WAN1_DNS1="$_live1"
	[ -n "$_live2" ] && WAN1_DNS2="$_live2"
	_w2=$(ifstatus wan2 2>/dev/null || true)
	_live3=$(echo "$_w2" | jsonfilter -e '@["dns-server"][0]' 2>/dev/null || true)
	[ -z "$_live3" ] && _live3=$(echo "$_w2" | jsonfilter -e '@["inactive"]["dns-server"][0]' 2>/dev/null || true)
	_live4=$(echo "$_w2" | jsonfilter -e '@["dns-server"][1]' 2>/dev/null || true)
	[ -z "$_live4" ] && _live4=$(echo "$_w2" | jsonfilter -e '@["inactive"]["dns-server"][1]' 2>/dev/null || true)
	[ -n "$_live3" ] && WAN2_DNS1="$_live3"
	[ -n "$_live4" ] && WAN2_DNS2="$_live4"
fi

uci -q set omr-tracker.wan1=interface
uci -q set omr-tracker.wan1.enabled='1'
uci -q set omr-tracker.wan1.type='dns'
uci -q delete omr-tracker.wan1.hosts 2>/dev/null || true
uci add_list omr-tracker.wan1.hosts="$WAN1_DNS1"
uci add_list omr-tracker.wan1.hosts="$WAN1_DNS2"

uci -q set omr-tracker.wan2=interface
uci -q set omr-tracker.wan2.enabled='1'
uci -q set omr-tracker.wan2.type="$WAN2_TRACKER_TYPE"
# Always clear per-type leftovers so switching type on re-run doesn't keep
# stale probe targets (hosts from a previous type=dns run, etc.).
uci -q delete omr-tracker.wan2.hosts 2>/dev/null || true
if [ "$WAN2_TRACKER_TYPE" = "dns" ]; then
	uci add_list omr-tracker.wan2.hosts="$WAN2_DNS1"
	uci add_list omr-tracker.wan2.hosts="$WAN2_DNS2"
fi

uci commit omr-tracker
/etc/init.d/omr-tracker restart
sleep 12

echo "wan1 tracker: type=dns hosts=$WAN1_DNS1 $WAN1_DNS2 state=$(uci -q get openmptcprouter.wan1.state)"
echo "wan2 tracker: type=$WAN2_TRACKER_TYPE state=$(uci -q get openmptcprouter.wan2.state)"
