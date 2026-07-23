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

# Install the persistent ISP-DNS policy helper.
# The helper re-derives live resolver IPs at boot (lease renewal can change them),
# so rc.local invokes logic instead of hardcoded IPs that go stale.
HELPER=/usr/lib/nexusgate/isp-dns-policy.sh
mkdir -p /usr/lib/nexusgate
# Write helper with a quoted heredoc so runtime variables survive intact.
# The fallback IP defaults below are interpolated NOW (install time) from the
# currently resolved values; everything else is literal and runs at boot time.
cat > "$HELPER" <<EOF
#!/bin/sh
# /usr/lib/nexusgate/isp-dns-policy.sh
# Policy-route ISP resolvers out their own WAN tables (6=wan1, 10=wan2).
# Re-derives live IPs from leases each run; falls back to deployment defaults.
# Priorities 89-92 are unique per IP - iproute drops rules at duplicate priorities,
# which silently loses one resolver and causes cross-WAN DNS leaks.
# peerdns=0 -> ISP DNS under "inactive"; active path covers peerdns=1.
set -u

WAN1_DNS1_DEF=${WAN1_DNS1}
WAN1_DNS2_DEF=${WAN1_DNS2}
WAN2_DNS1_DEF=${WAN2_DNS1}
WAN2_DNS2_DEF=${WAN2_DNS2}

WAN1_DNS1=\$WAN1_DNS1_DEF
WAN1_DNS2=\$WAN1_DNS2_DEF
WAN2_DNS1=\$WAN2_DNS1_DEF
WAN2_DNS2=\$WAN2_DNS2_DEF

if command -v jsonfilter >/dev/null 2>&1; then
	_w1=\$(ifstatus wan1 2>/dev/null || true)
	_l1=\$(echo "\$_w1" | jsonfilter -e '@["dns-server"][0]' 2>/dev/null || true)
	[ -z "\$_l1" ] && _l1=\$(echo "\$_w1" | jsonfilter -e '@["inactive"]["dns-server"][0]' 2>/dev/null || true)
	_l2=\$(echo "\$_w1" | jsonfilter -e '@["dns-server"][1]' 2>/dev/null || true)
	[ -z "\$_l2" ] && _l2=\$(echo "\$_w1" | jsonfilter -e '@["inactive"]["dns-server"][1]' 2>/dev/null || true)
	[ -n "\$_l1" ] && WAN1_DNS1="\$_l1"
	[ -n "\$_l2" ] && WAN1_DNS2="\$_l2"
	_w2=\$(ifstatus wan2 2>/dev/null || true)
	_l3=\$(echo "\$_w2" | jsonfilter -e '@["dns-server"][0]' 2>/dev/null || true)
	[ -z "\$_l3" ] && _l3=\$(echo "\$_w2" | jsonfilter -e '@["inactive"]["dns-server"][0]' 2>/dev/null || true)
	_l4=\$(echo "\$_w2" | jsonfilter -e '@["dns-server"][1]' 2>/dev/null || true)
	[ -z "\$_l4" ] && _l4=\$(echo "\$_w2" | jsonfilter -e '@["inactive"]["dns-server"][1]' 2>/dev/null || true)
	[ -n "\$_l3" ] && WAN2_DNS1="\$_l3"
	[ -n "\$_l4" ] && WAN2_DNS2="\$_l4"
fi

# Flush our priority slots BEFORE adding: lease renewals change resolver IPs,
# and stale rules at 89-92 both leak DNS out the wrong WAN and make the
# subsequent 'ip rule add priority 89-92' fail silently. Loop because iproute
# permits multiple rules per priority.
for _p in 89 90 91 92; do
	while ip rule show | grep -q "^\$_p:"; do
		ip rule del priority "\$_p" 2>/dev/null || break
	done
done
_add() { ip rule add priority "\$3" to "\$1" lookup "\$2" 2>/dev/null || true; }
_add "\$WAN1_DNS1" 6  89
_add "\$WAN1_DNS2" 6  90
_add "\$WAN2_DNS1" 10 91
_add "\$WAN2_DNS2" 10 92
EOF
chmod +x "$HELPER"

# Apply policy rules live now using the installed helper.
"$HELPER"

# Persist across reboot: invoke the helper so boot always re-derives live IPs
# (hardcoded IPs go stale on lease renewal and route the new resolver out the
# wrong WAN, reproducing the i/o-timeout DNS leak).
#
# Normalize the rc.local DNS-policy persistence idempotently. This MIGRATES boxes
# that ran the old installer (which wrote the MARK plus 4 hardcoded resolver-IP
# rules) to the re-derivation helper, and is safe to re-run.
RC=/etc/rc.local
MARK="# nexusgate-isp-dns-policy"
if [ -f "$RC" ]; then
	# strip any prior nexusgate DNS-policy lines: the MARK, legacy hardcoded
	# resolver rules (priorities 89-92 -> tables 6/10), and any prior helper call.
	# Use | as the sed address delimiter: MARK begins with # and HELPER contains
	# /, so neither # nor / is a safe delimiter; neither string contains |.
	sed -i "\\|$MARK|d" "$RC"
	sed -i '/ip rule add priority 89 to .* lookup 6/d; /ip rule add priority 90 to .* lookup 6/d; /ip rule add priority 91 to .* lookup 10/d; /ip rule add priority 92 to .* lookup 10/d' "$RC"
	sed -i "\\|$HELPER|d" "$RC"
	# (re)insert MARK + helper call before exit 0
	sed -i "/^exit 0/i $MARK" "$RC"
	sed -i "/^exit 0/i $HELPER 2>/dev/null || true" "$RC"
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
dig @10.25.0.1 google.com.br +time=3 +short | head -1 || true
