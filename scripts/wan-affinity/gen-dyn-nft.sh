#!/bin/sh
# /usr/lib/wan-affinity/gen-dyn-nft.sh
#
# Regenerate and atomically load the DYNAMIC balanced-steering nft table
# (table inet wan_affinity_dyn). Called by:
#   - apply-affinity.sh   when the balanced.list membership changes
#   - 098-wan-affinity    when the spillover steering target flips
#
# Usage: gen-dyn-nft.sh wan1|wan2
#   argument = target WAN for NEW balanced-policy connections.
#
# MARK OWNERSHIP CONTRACT -- full owned-mask inventory from the LIVE router
# (ip rule + ip -6 rule + nft ruleset, nft v1.0.7):
#   OMR core:   exact 32-bit fwmark matches 0x4539*/0x6539* (no mask)
#   Tailscale:  match 0x80000/0xff0000; set: mark & 0xffff04ff | 0x400
#               (tests VALUE 0x08 in byte 16-23; our 0x01/0x02/0x03 in that
#               byte can never alias it, and 0x80000-marked packets are
#               rejected by our foreign-bits guard anyway)
#   SNAT gate:  match mark & 0x0000ff00 == 0x400 (bits 8-15, disjoint)
#   This chain: bits 16-17 only (mask 0x30000)
# No bit range is globally unclaimed (0xff0000 + exact matches cover all),
# so safety comes from the dual-register exclusion predicate, not from bit
# choice alone. OMR exact-match marks DO carry bits inside 0x30000, but
#       (meta mark & 0xfffcffff) == 0  AND  (ct mark & 0xfffcffff) == 0
# provably rejects every inventoried foreign mark before any restore/pick/
# save runs: 0x453913 & 0xfffcffff = 0x443913 != 0.
# NEVER weaken these guards to a bare 0x30000 test -- OMR marks like 0x453913
# have bit 16 SET (0x453913 & 0x30000 = 0x10000), so a mask-only match would
# misclassify OMR traffic as WAN1-affine, and OR-ing 0x20000 into 0x453913
# would break OMR's exact-match fwmark rules (0x453913 -> 0x473913).
#
# DIRECTION GUARD: chain hooks all of prerouting, but ct-mark restore on
# WAN-ingress reply packets would send replies to fwmark rules 40/41 and
# misroute them. First rule bails on anything not entering via br-lan.
#
# STICKINESS: balanced flows save their affinity bits into ct mark (masked to
# 0x30000 -- never a full-mark copy, OMR may write other ct bits later) and
# every subsequent packet restores from it, so a steering flip only affects
# NEW connections. Existing flows keep their NAT public IP until they end.
#
# IDEMPOTENT LOAD (verified 3x consecutive on router, nft v1.0.7): the file
# opens with a bare `table` declaration then `delete table` -- on nft >= 0.9
# a bare declaration is create-if-absent (never "File exists"), so delete
# always has a target and the whole file applies as one transaction.

set -eu

WA_DIR=${WA_DIR:-/etc/wan-affinity}
BAL_LIST="$WA_DIR/balanced.list"

TARGET=${1:-wan1}
case "$TARGET" in
	wan1) TMARK=0x10000 ;;
	wan2) TMARK=0x20000 ;;
	*) echo "usage: $0 wan1|wan2" >&2; exit 1 ;;
esac

# Read list -> space-separated validated lowercase MACs (same contract as
# apply-affinity.sh; abort on malformed rather than guess).
MACS=""
if [ -f "$BAL_LIST" ]; then
	while IFS= read -r line; do
		m=$(echo "$line" | sed 's/#.*//; s/[[:space:]]//g' | tr 'A-F' 'a-f')
		[ -z "$m" ] && continue
		echo "$m" | grep -qE '^([0-9a-f]{2}:){5}[0-9a-f]{2}$' || {
			echo "ERROR: invalid MAC '$line' in $BAL_LIST" >&2
			exit 1
		}
		MACS="$MACS$m "
	done < "$BAL_LIST"
fi

SET=""
for m in $MACS; do
	if [ -z "$SET" ]; then SET="$m"; else SET="$SET, $m"; fi
done

TMP=$(mktemp /tmp/.wa-dyn.XXXXXX)
trap 'rm -f "$TMP"' EXIT

{
	# declare-then-delete makes the load idempotent whether or not the table
	# already exists; the whole file applies as ONE transaction (no window
	# where balanced traffic is unmarked).
	echo "table inet wan_affinity_dyn"
	echo "delete table inet wan_affinity_dyn"
	if [ -n "$SET" ]; then
		cat <<EOF
table inet wan_affinity_dyn {
	chain balance {
		type filter hook prerouting priority -149; policy accept;
		iifname != "br-lan" return comment "LAN-origin only: never mark WAN-ingress replies"
		meta mark & 0xfffcffff != 0 return comment "foreign (OMR) packet mark: hands off"
		meta mark & 0x30000 != 0 return comment "already pinned by wan_affinity static chain"
		ether saddr != { $SET } return comment "not a balanced-policy device"
		ct mark & 0xfffcffff != 0 return comment "foreign (OMR) ct mark: hands off"
		ct mark & 0x10000 != 0 meta mark set meta mark | 0x10000 counter return comment "sticky restore wan1"
		ct mark & 0x20000 != 0 meta mark set meta mark | 0x20000 counter return comment "sticky restore wan2"
		ct state new meta mark set meta mark | $TMARK ct mark set ct mark | $TMARK counter comment "balanced new flow -> $TARGET"
	}
}
EOF
	fi
} > "$TMP"

nft -c -f "$TMP" || { echo "ERROR: generated dyn nft failed syntax check ($TMP kept)" >&2; trap - EXIT; exit 1; }
nft -f "$TMP"
