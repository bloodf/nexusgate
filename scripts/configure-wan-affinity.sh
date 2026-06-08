#!/bin/sh
# Configure per-device WAN affinity on NexusGate (OpenMPTCProuter, dual-WAN, no
# VPS bonding). Replaces the ECMP load-balancer (099-ecmp-balance) and the older
# 098-vivo-pin with a deterministic, single-nexthop-per-device model:
#
#   - Vivo (wan1) is the DEFAULT WAN for every LAN device.
#   - MACs in CLARO_MACS are routed via Claro (wan2)  (mark 0x20000 -> table 101).
#   - MACs in VIVO_MACS are explicitly pinned to Vivo (mark 0x10000 -> table 100).
#   - Each table holds ONE nexthop, so a device's flows never split across two
#     public IPs mid-session -> streaming/gaming stay stable.
#   - Automatic failover + shift-back is handled by 098-wan-affinity each tracker
#     tick (rewrites the single nexthop of tables 100/101 from live WAN state).
#
# This installer seeds the persistent lock lists (the source of truth), installs
# the shared apply helper, the failover hook, and the device-management web UI,
# then applies everything. After first install the lists become authoritative:
# re-running this script will NOT clobber edits made via the web UI (it seeds a
# list only when that list file is absent). Delete a list to reset it from env.
#
# Files installed:
#   /etc/wan-affinity/{claro,vivo}.list      lock lists (source of truth)
#   /etc/wan-affinity/names.list             device friendly names (created empty)
#   /usr/lib/wan-affinity/apply-affinity.sh  lists -> nft + routing (live)
#   /usr/lib/wan-affinity/oui.db             offline OUI vendor lookup database
#   /usr/share/omr/post-tracking.d/098-wan-affinity   failover hook
#   /www/cgi-bin/wan-affinity                web UI (http://192.168.100.1/cgi-bin/wan-affinity)
#
# Idempotent. Backs up replaced files. Re-run after OMR package upgrades.
#
# Usage:
#   CLARO_MACS="aa:bb:cc:dd:ee:ff 11:22:33:44:55:66" sh configure-wan-affinity.sh
#   VIVO_MACS="..." overrides the Vivo seed list (defaults to current deployment).
#
# Deploy from a workstation (scp is unavailable on this router) - the companion
# files live in scripts/wan-affinity/ next to this script; copy the whole dir, or
# cat each file to its destination, then run this installer.

set -eu

# ---- Seed lock lists (used only when a list file does not yet exist) ---------
CLARO_MACS=${CLARO_MACS:-"40:f6:bc:38:df:7c 44:d5:cc:e5:ad:a7 1c:fe:2b:f3:84:fc a8:a0:92:2f:9a:dc"}
VIVO_MACS=${VIVO_MACS:-"06:72:3d:90:06:10 22:f6:ca:e4:09:46 34:29:8f:70:87:c8 48:e1:ca:06:f4:12 4e:42:43:17:1d:6f a4:6b:40:32:23:20 bc:35:1e:a3:f1:5d be:53:2a:62:8b:dd e0:85:4d:46:3d:6e f4:d4:88:66:07:9c fa:b3:8b:3c:da:f1"}

WA_DIR=/etc/wan-affinity
LIB_DIR=/usr/lib/wan-affinity
NFT_DIR=/etc/nftables.d
PT_DIR=/usr/share/omr/post-tracking.d
PT_FILE="$PT_DIR/098-wan-affinity"
APPLY="$LIB_DIR/apply-affinity.sh"
CGI=/www/cgi-bin/wan-affinity
SRC="$(dirname "$0")/wan-affinity"
TS=$(date +%s)

# ---- Validate + lowercase a space-separated MAC list (never guess a MAC) -----
_clean_macs() {
	_out=""
	for m in $1; do
		ml=$(echo "$m" | tr 'A-F' 'a-f')
		echo "$ml" | grep -qE '^([0-9a-f]{2}:){5}[0-9a-f]{2}$' || {
			echo "ERROR: invalid MAC '$m' (expected aa:bb:cc:dd:ee:ff)" >&2
			exit 1
		}
		_out="$_out$ml
"
	done
	printf '%s' "$_out"
}

# ---- 1. Seed lists if absent ------------------------------------------------
mkdir -p "$WA_DIR"
[ -f "$WA_DIR/claro.list" ] || _clean_macs "$CLARO_MACS" | sort -u > "$WA_DIR/claro.list"
[ -f "$WA_DIR/vivo.list" ]  || _clean_macs "$VIVO_MACS"  | sort -u > "$WA_DIR/vivo.list"

# Seed names.list (device friendly names) if absent. Never clobber existing.
[ -f "$WA_DIR/names.list" ] || touch "$WA_DIR/names.list"

# ---- 2. Install helper, failover hook, web UI, OUI database -----------------
mkdir -p "$LIB_DIR" "$PT_DIR" /www/cgi-bin
if [ -d "$SRC" ]; then
	for pair in \
		"apply-affinity.sh:$APPLY" \
		"098-wan-affinity:$PT_FILE" \
		"wan-affinity.cgi:$CGI"; do
		s="$SRC/${pair%%:*}"; d=${pair#*:}
		if [ -f "$s" ]; then
			[ -f "$d" ] && cp "$d" "$d.bak.$TS"
			cp "$s" "$d"
			chmod +x "$d"
		fi
	done

	# oui.db is a data file (not executable); deploy separately
	if [ -f "$SRC/oui.db" ]; then
		[ -f "$LIB_DIR/oui.db" ] && cp "$LIB_DIR/oui.db" "$LIB_DIR/oui.db.bak.$TS"
		cp "$SRC/oui.db" "$LIB_DIR/oui.db"
		echo "Installed oui.db ($(wc -l < "$LIB_DIR/oui.db") entries)."
	else
		echo "NOTE: $SRC/oui.db not found - vendor lookup will be unavailable in the UI." >&2
	fi
else
	echo "NOTE: companion dir $SRC not found - assuming apply/098/cgi/oui already deployed." >&2
fi

# ---- 3. Retire superseded artifacts -----------------------------------------
[ -f "$NFT_DIR/20-vivo-pin.nft" ] && mv "$NFT_DIR/20-vivo-pin.nft" "$NFT_DIR/20-vivo-pin.nft.retired.$TS"
for f in 098-vivo-pin 099-ecmp-balance; do
	[ -f "$PT_DIR/$f" ] && mv "$PT_DIR/$f" "$PT_DIR/$f.retired.$TS"
done
for f in "$PT_DIR"/099-ecmp-balance.bak-*; do
	[ -f "$f" ] && rm -f "$f"
done

# ---- 4. Apply ---------------------------------------------------------------
if [ -x "$APPLY" ]; then
	"$APPLY"
else
	echo "ERROR: $APPLY not installed; cannot apply." >&2
	exit 1
fi

# ---- 5. Report --------------------------------------------------------------
echo "== lock lists =="
echo "claro.list:"; sed 's/^/  /' "$WA_DIR/claro.list"
echo "vivo.list:";  sed 's/^/  /' "$WA_DIR/vivo.list"
echo
echo "== nft chain =="
nft list chain inet fw4 wan_affinity 2>/dev/null || echo "(wan_affinity chain not loaded - check fw4 reload)"
echo
echo "== ip rules (affinity) =="
ip rule show | grep -E "lookup (100|101)|iif br-lan" || true
echo
echo "== table 100 (WAN1 default) =="; ip route show table 100
echo "== table 101 (WAN2) =="; ip route show table 101
echo
echo "Web UI: http://192.168.100.1/cgi-bin/wan-affinity"
echo "Done. Verify a WAN2 device shows the WAN2 public IP and a default device"
echo "shows the WAN1 public IP, both stable across repeated calls."
