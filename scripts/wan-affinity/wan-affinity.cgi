#!/bin/sh
# /www/cgi-bin/wan-affinity  (uhttpd CGI)
#
# Device-management web UI for per-device WAN affinity.
#
# MODE 1  GET (no api param)   -> HTML shell; JS fetches data via fetch()
# MODE 2  GET ?api=devices     -> JSON device list + meta
# MODE 3  POST                 -> apply changes, return JSON {ok,msg}
#
# DUAL-MODE DESIGN (fixes the browser-refresh POST-resubmit problem):
#   The HTML page is served by GET and contains NO server-rendered device rows.
#   All mutations go through fetch(POST), so a browser reload never re-submits.
#
# POST WIRE FORMAT:
#   action=save (default / no action field): field "pairs", value = comma-separated
#     MAC|w tokens where w is v (wan1/vivo), c (wan2/claro), b (balanced/Auto
#     spillover pool), or d/absent (default).
#     Example decoded: aa:bb:cc:dd:ee:ff|c,11:22:33:44:55:66|v
#   action=rename: fields "mac" and "name". Updates names.list.
#     Returns {"ok":true,"msg":"Name saved."} or {"ok":false,"msg":"..."}.
#   action=capacity: fields wan1_down_mbps wan1_up_mbps wan2_down_mbps
#     wan2_up_mbps hi_pct lo_pct cooldown_s. ALL fields validated before ANY
#     uci write (same constraints 098-wan-affinity enforces: Mbps > 0,
#     0 < lo_pct < hi_pct <= 100, cooldown_s unsigned). Whole POST rejected on
#     any invalid field - never a partial commit. On success commits uci and
#     runs apply-affinity.sh so steering state updates immediately.
#
# Device discovery: /tmp/dhcp.leases (IP/MAC/name) merged with any locked MACs
#   that are currently offline (so a device lock is never silently dropped).
# Current WAN per device: read from the lock lists (same source of truth as
#   apply-affinity.sh), so the page always shows the effective state.
#
# PROVIDER-AGNOSTIC LABELS: wan1_label / wan2_label read from uci with fallback
#   to "WAN1" / "WAN2". On-disk list files stay named vivo.list / claro.list
#   (live apply contract - do not rename). Only user-facing strings change.
#
# LIST-FILE MAPPING (preserve; apply-affinity.sh depends on this):
#   vivo.list  = wan1  = mark 0x10000 = table 100
#   claro.list = wan2  = mark 0x20000 = table 101
#
# Unauthenticated by design: this is the trusted LAN / Tailscale admin surface,
#   same posture as LuCI on this box (uhttpd input is firewalled off the WANs).
#   The previous Vivo/Claro ISP names were internal deployment details; the UI
#   now uses provider-agnostic labels so the same script works on any dual-WAN
#   NexusGate deployment.
#
# NEW (v2):
#   - Offline OUI vendor lookup via /usr/lib/wan-affinity/oui.db for nameless
#     devices (deployed by configure-wan-affinity.sh).
#   - Editable device names persisted in /etc/wan-affinity/names.list.
#     Renaming does NOT call apply-affinity.sh (names don't affect routing).
#   - Live per-device up/down Kbps from conntrack dual-sample (~1s added latency
#     to api=devices). No background daemon required.

WA_DIR=/etc/wan-affinity
CLARO_LIST="$WA_DIR/claro.list"
VIVO_LIST="$WA_DIR/vivo.list"
NAMES_LIST="$WA_DIR/names.list"
BAL_LIST="$WA_DIR/balanced.list"
APPLY=/usr/lib/wan-affinity/apply-affinity.sh
OUI_DB=/usr/lib/wan-affinity/oui.db
LEASES=/tmp/dhcp.leases

mkdir -p "$WA_DIR"

# %XX + '+' -> bytes
urldecode() {
	s=$(printf '%s' "$1" | sed 's/+/ /g; s/%/\\x/g')
	printf '%b' "$s"
}

# lowercase + validate; echoes the mac on success, empty on failure
norm_mac() {
	# Trust boundary: reject any input containing CR/LF outright — a split or
	# multiline MAC must never be silently repaired into a valid one.
	case "$1" in *"$(printf '\r')"* ) return 1 ;; esac
	[ "$(printf '%s' "$1" | wc -l)" -eq 0 ] || return 1
	# Canonicalize: lowercase, strip blanks; require the ENTIRE result to be
	# exactly one MAC (grep -x on a single line). Output is always canonical.
	# NOTE: '[:space:]' as a tr operand is malformed everywhere (classes are
	# only valid inside a bracket set), so tr deletes those LITERAL chars —
	# mangling the MAC. Use explicit space+tab for portability.
	m=$(printf '%s' "$1" | tr 'A-F' 'a-f' | tr -d ' \011')
	printf '%s\n' "$m" | grep -qxE '([0-9a-f]{2}:){5}[0-9a-f]{2}' || return 1
	printf '%s' "$m"
}

# JSON-escape an arbitrary string: escape backslash, double-quote, tab, CR, LF.
# awk (not sed) because busybox/POSIX sed holds inter-line LF outside the pattern
# space, so s/\n// rules are dead code and raw newlines leak into the JSON. awk
# iterates records and re-emits the LF as an escaped \n via the NR>1 join, so the
# full buffer - including embedded newlines from apply-error output - is encoded
# structurally safe. Names are sanitized before storage; this hardens the envelope.
jsonesc() {
	printf '%s' "$1" | awk 'BEGIN{ORS=""} {gsub(/\\/,"\\\\");gsub(/"/,"\\\"");gsub(/\t/,"\\t");gsub(/\r/,"\\r"); if(NR>1) printf "\\n"; printf "%s",$0}'
}

in_list() { # mac listfile
	[ -f "$2" ] && grep -qiE "^[[:space:]]*$1[[:space:]]*$" "$2"
}

# Look up OUI vendor for a MAC address. Returns vendor string or empty.
# Only called for devices with no resolved name (avoids awk startup cost per row).
oui_vendor() { # mac -> vendor string or empty
	[ -f "$OUI_DB" ] || return 0
	p=$(printf '%s' "$1" | tr -d ':' | cut -c1-6 | tr 'a-f' 'A-F')
	awk -F'\t' -v k="$p" '$1==k{print $2; exit}' "$OUI_DB"
}

# Read custom device name from names.list (format: mac|name per line).
cname() { # mac -> custom name or empty
	[ -f "$NAMES_LIST" ] || return 0
	awk -F'|' -v m="$1" '$1==m{sub(/^[^|]*\|/,""); print; exit}' "$NAMES_LIST"
}

# ---- read provider labels (provider-agnostic) ----------------------------------
wan1_label=$(uci -q get network.wan1.label 2>/dev/null || true)
wan2_label=$(uci -q get network.wan2.label 2>/dev/null || true)
[ -z "$wan1_label" ] && wan1_label="WAN1"
[ -z "$wan2_label" ] && wan2_label="WAN2"

# ---- MODE 3: POST -> apply changes, return JSON --------------------------------
if [ "${REQUEST_METHOD:-GET}" = "POST" ]; then
	# CSRF / same-origin guard: state-changing POST must come from the same origin.
	# A browser fetch() always sends Origin; fall back to Referer host when absent.
	# Fail closed: if HTTP_HOST is empty, or neither Origin nor Referer resolves to
	# a matching host, reject the request before any header or body output.
	_req_host=""
	if [ -n "${HTTP_ORIGIN:-}" ]; then
		# Strip scheme: "http://host:port/..." -> "host:port"
		_no_scheme="${HTTP_ORIGIN#*://}"
		_req_host="${_no_scheme%%/*}"
	elif [ -n "${HTTP_REFERER:-}" ]; then
		_no_scheme="${HTTP_REFERER#*://}"
		_req_host="${_no_scheme%%/*}"
	fi
	if [ -z "${HTTP_HOST:-}" ] || [ "$_req_host" != "$HTTP_HOST" ]; then
		printf 'Status: 403 Forbidden\r\n'
		printf 'Content-Type: application/json\r\n\r\n'
		printf '{"ok":false,"msg":"cross-origin request rejected"}'
		exit 0
	fi

	printf 'Content-Type: application/json\r\n\r\n'

	# Guard non-numeric CONTENT_LENGTH and clamp to a sane cap. Unbounded dd would
	# buffer the whole body in RAM on a memory-constrained router (DoS vector).
	len=${CONTENT_LENGTH:-0}
	case "$len" in ''|*[!0-9]*) len=0 ;; esac
	[ "$len" -gt 65536 ] && len=65536
	body=$(dd bs=1 count="$len" 2>/dev/null)

	# Extract fields from urlencoded body (single pass, no eval)
	pairs_raw=""
	post_action=""
	post_mac=""
	post_name=""
	cap_w1d=""
	cap_w1u=""
	cap_w2d=""
	cap_w2u=""
	cap_hi=""
	cap_lo=""
	cap_cd=""
	# set -f disables glob expansion: a bare `*` token in the body would otherwise
	# expand to filenames during the unquoted `for kv in $body` split.
	set -f
	OLD_IFS=$IFS
	IFS='&'
	for kv in $body; do
		k="${kv%%=*}"
		v="${kv#*=}"
		dk=$(urldecode "$k")
		dv=$(urldecode "$v")
		case "$dk" in
			action) post_action="$dv" ;;
			pairs)  pairs_raw="$dv" ;;
			mac)    post_mac="$dv" ;;
			name)   post_name="$dv" ;;
			wan1_down_mbps) cap_w1d="$dv" ;;
			wan1_up_mbps)   cap_w1u="$dv" ;;
			wan2_down_mbps) cap_w2d="$dv" ;;
			wan2_up_mbps)   cap_w2u="$dv" ;;
			hi_pct)     cap_hi="$dv" ;;
			lo_pct)     cap_lo="$dv" ;;
			cooldown_s) cap_cd="$dv" ;;
		esac
	done
	IFS=$OLD_IFS
	set +f

	# ---- action=rename: update device friendly name ----------------------------
	if [ "$post_action" = "rename" ]; then
		cm=$(norm_mac "$post_mac")
		if [ -z "$cm" ]; then
			printf '{"ok":false,"msg":"Invalid MAC address."}'
			exit 0
		fi

		# SANITIZE name hard: hostile free-text written to disk and re-served as JSON.
		# 1. Strip ALL CR and LF - newlines would inject extra mac|name lines (critical).
		# 2. Strip pipe - field separator in names.list.
		# 3. Collapse runs of whitespace to single space, trim edges.
		# 4. Cap at 48 chars.
		safe_name=$(printf '%s' "$post_name" \
			| tr -d '\r\n|' \
			| sed 's/[[:space:]][[:space:]]*/ /g; s/^[[:space:]]*//; s/[[:space:]]*$//' \
			| cut -c1-48)

		# Atomically rewrite names.list: write all lines except the existing entry
		# for this mac, then append the new one (skip if empty = delete custom name).
		# Temp MUST live in the same filesystem as the target so the final mv is a
		# rename (atomic), not a cross-fs copy+unlink. /tmp is tmpfs and /etc is an
		# overlay, so mktemp /tmp/... would make mv non-atomic and risk truncation.
		touch "$NAMES_LIST" 2>/dev/null || true
		tmp=$(mktemp "$WA_DIR/.names.XXXXXX")
		awk -F'|' -v m="$cm" '$1!=m{print}' "$NAMES_LIST" > "$tmp" 2>/dev/null || true
		if [ -n "$safe_name" ]; then
			printf '%s|%s\n' "$cm" "$safe_name" >> "$tmp"
		fi
		mv "$tmp" "$NAMES_LIST"

		printf '{"ok":true,"msg":"Name saved."}'
		exit 0
	fi

	# ---- action=capacity: per-WAN capacity + steering thresholds ---------------
	# Validate EVERYTHING first, then write. Constraints mirror the consumer
	# (098-wan-affinity): positive integer Mbps for all four capacities,
	# 0 < lo_pct < hi_pct <= 100, cooldown_s unsigned integer. A single invalid
	# field rejects the whole POST with NO uci mutation, so the hook never sees
	# a half-written capacity section (its silent defaulting would mask the bug).
	if [ "$post_action" = "capacity" ]; then
		_pnum() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -gt 0 ]; }
		_puint() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; return 0; }

		for _cv in "$cap_w1d" "$cap_w1u" "$cap_w2d" "$cap_w2u"; do
			if ! _pnum "$_cv"; then
				printf '{"ok":false,"msg":"All four capacities must be whole Mbps > 0."}'
				exit 0
			fi
		done
		if ! _pnum "$cap_hi" || ! _pnum "$cap_lo" \
			|| [ "$cap_hi" -gt 100 ] || [ "$cap_lo" -ge "$cap_hi" ]; then
			printf '{"ok":false,"msg":"Thresholds must satisfy 0 < low < high <= 100."}'
			exit 0
		fi
		if ! _puint "$cap_cd"; then
			printf '{"ok":false,"msg":"Cooldown must be a whole number of seconds (0 allowed)."}'
			exit 0
		fi

		# All valid -> write. The capacity SECTION must exist before any
		# option set: nothing in the repo seeds the wan_affinity package, and
		# `uci set p.s.o=v` fails when section s is absent.
		if ! uci -q get wan_affinity.capacity >/dev/null 2>&1; then
			touch /etc/config/wan_affinity 2>/dev/null || true
			if ! uci -q set wan_affinity.capacity=capacity; then
				printf '{"ok":false,"msg":"uci: cannot create capacity section."}'
				exit 0
			fi
		fi
		# Every set must succeed BEFORE commit: a failed set with a successful
		# commit would report success while persisting missing/stale options.
		# On any failure, revert the staged changes so nothing partial lingers.
		if ! { uci -q set wan_affinity.capacity.wan1_down_mbps="$cap_w1d" \
			&& uci -q set wan_affinity.capacity.wan1_up_mbps="$cap_w1u" \
			&& uci -q set wan_affinity.capacity.wan2_down_mbps="$cap_w2d" \
			&& uci -q set wan_affinity.capacity.wan2_up_mbps="$cap_w2u" \
			&& uci -q set wan_affinity.capacity.hi_pct="$cap_hi" \
			&& uci -q set wan_affinity.capacity.lo_pct="$cap_lo" \
			&& uci -q set wan_affinity.capacity.cooldown_s="$cap_cd"; }; then
			uci -q revert wan_affinity 2>/dev/null || true
			printf '{"ok":false,"msg":"uci set failed; capacity not saved."}'
			exit 0
		fi
		if ! uci -q commit wan_affinity; then
			printf '{"ok":false,"msg":"uci commit failed."}'
			exit 0
		fi

		# Run the shared apply path so steering activates/deactivates NOW;
		# merely committing would wait for the next tracker tick.
		if [ -x "$APPLY" ]; then
			if out=$("$APPLY" 2>&1); then
				printf '{"ok":true,"msg":"Capacities saved. Steering config is live."}'
			else
				safe=$(jsonesc "$out")
				printf '{"ok":false,"msg":"Saved, but apply error: %s"}' "$safe"
			fi
		else
			printf '{"ok":true,"msg":"Capacities saved (apply helper missing; live at next tracker tick)."}'
		fi
		exit 0
	fi

	# Reject unknown nonempty action values BEFORE the bulk-save fallthrough.
	# Without this, a typo'd or future action that carries no "pairs" field
	# would fall through to bulk-save with an empty pairs_raw and silently
	# wipe the lock/balanced lists. Empty action and "save" are the two
	# spellings the shipped UI uses.
	if [ -n "$post_action" ] && [ "$post_action" != "save" ]; then
		safe_act=$(jsonesc "$post_action")
		printf '{"ok":false,"msg":"Unknown action: %s"}' "$safe_act"
		exit 0
	fi

	# ---- action=save (default): bulk WAN assignment ----------------------------
	# Parse: split on comma, then split each token on pipe. Duplicate MACs in one
	# POST (e.g. "same|v,same|c") are resolved LAST-TOKEN-WINS via the awk map
	# below, so a MAC can never land in both lists (cross-list overlap would make
	# the effective pin depend on list-check ordering elsewhere).
	assign=""
	OLD_IFS=$IFS
	IFS=','
	for token in $pairs_raw; do
		mac_part="${token%%|*}"
		wan_part="${token#*|}"
		[ "$wan_part" = "$token" ] && wan_part="d"  # no pipe -> default
		cm=$(norm_mac "$mac_part")
		[ -z "$cm" ] && continue  # discard invalid MACs silently
		case "$wan_part" in
			v|c|b) assign="$assign$cm $wan_part
" ;;
			*)   assign="$assign$cm d
" ;;  # d or anything else -> default (not in any list)
		esac
	done
	IFS=$OLD_IFS

	# Last assignment per MAC wins; then split into per-list membership.
	final=$(printf '%s' "$assign" | awk '{w[$1]=$2} END{for(m in w) print m, w[m]}')
	newvivo=$(printf '%s\n' "$final"  | awk '$2=="v"{print $1}')
	newclaro=$(printf '%s\n' "$final" | awk '$2=="c"{print $1}')
	newbal=$(printf '%s\n' "$final"   | awk '$2=="b"{print $1}')

	# Atomic list writes: temp in $WA_DIR so mv is a same-filesystem rename (not a
	# cross-fs copy), matching the names.list pattern at lines 164-169 above.
	# PREPARE-THEN-COMMIT: both temp files are fully written and flushed BEFORE
	# either rename, so the only non-atomic window is the two back-to-back mv
	# calls (individual mvs are atomic; the pair is not). A crash exactly between
	# them leaves new vivo.list + old claro.list, but never a partial file, and
	# last-token-wins above guarantees the two new lists are disjoint so the
	# worst case is one stale (pre-existing) pin, not a cross-list conflict
	# introduced by this save.
	_tmp_vivo=$(mktemp "$WA_DIR/.vivo.XXXXXX")
	_tmp_claro=$(mktemp "$WA_DIR/.claro.XXXXXX")
	_tmp_bal=$(mktemp "$WA_DIR/.balanced.XXXXXX")
	printf '%s' "$newvivo"  | sed '/^$/d' | sort -u > "$_tmp_vivo"
	printf '%s' "$newclaro" | sed '/^$/d' | sort -u > "$_tmp_claro"
	printf '%s' "$newbal"   | sed '/^$/d' | sort -u > "$_tmp_bal"
	mv "$_tmp_vivo" "$VIVO_LIST"
	mv "$_tmp_claro" "$CLARO_LIST"
	mv "$_tmp_bal" "$BAL_LIST"

	if [ -x "$APPLY" ]; then
		if out=$("$APPLY" 2>&1); then
			printf '{"ok":true,"msg":"Saved and applied. Routing is live."}'
		else
			safe=$(jsonesc "$out")
			printf '{"ok":false,"msg":"apply error: %s"}' "$safe"
		fi
	else
		printf '{"ok":false,"msg":"ERROR: %s missing - run configure-wan-affinity.sh."}' "$APPLY"
	fi
	exit 0
fi

# ---- MODE 2: GET ?api=devices -> JSON device list + meta ----------------------
case "${QUERY_STRING:-}" in
	*api=devices*)
		printf 'Content-Type: application/json\r\n\r\n'

		NEIGH=$(ip neigh show 2>/dev/null)
		is_online() { echo "$NEIGH" | grep -qE "^$1 .*(REACHABLE|STALE|DELAY|PROBE)"; }

		# meta: table 100/101 egress device names
		t100=$(ip route show table 100 2>/dev/null | awk '/^default/{print $5; exit}')
		t101=$(ip route show table 101 2>/dev/null | awk '/^default/{print $5; exit}')
		[ -n "$t100" ] || t100="(down)"
		[ -n "$t101" ] || t101="(down)"

		w1l=$(jsonesc "$wan1_label")
		w2l=$(jsonesc "$wan2_label")
		t100e=$(jsonesc "$t100")
		t101e=$(jsonesc "$t101")

		# ---- capacity config + balanced-steering state for the UI ----------------
		# Numbers are validated before interpolation into JSON: any missing or
		# non-numeric uci value becomes JSON null, never raw shell text.
		_jnum() { case "$1" in ''|*[!0-9]*) printf 'null' ;; *) printf '%s' "$1" ;; esac; }
		mc_w1d=$(uci -q get wan_affinity.capacity.wan1_down_mbps 2>/dev/null || true)
		mc_w1u=$(uci -q get wan_affinity.capacity.wan1_up_mbps   2>/dev/null || true)
		mc_w2d=$(uci -q get wan_affinity.capacity.wan2_down_mbps 2>/dev/null || true)
		mc_w2u=$(uci -q get wan_affinity.capacity.wan2_up_mbps   2>/dev/null || true)
		mc_hi=$(uci -q get wan_affinity.capacity.hi_pct 2>/dev/null || true)
		mc_lo=$(uci -q get wan_affinity.capacity.lo_pct 2>/dev/null || true)
		mc_cd=$(uci -q get wan_affinity.capacity.cooldown_s 2>/dev/null || true)

		# steering configured = all four capacities are positive ints (mirrors the
		# 098-wan-affinity hard gate); active additionally needs a non-empty
		# balanced.list with at least one MAC-ish line and the generator present.
		_cfg=false
		case "$mc_w1d" in ''|0|*[!0-9]*) : ;; *) case "$mc_w1u" in ''|0|*[!0-9]*) : ;; *)
		case "$mc_w2d" in ''|0|*[!0-9]*) : ;; *) case "$mc_w2u" in ''|0|*[!0-9]*) : ;; *)
			_cfg=true ;; esac ;; esac ;; esac ;; esac
		# _ready mirrors the hook's _bal_active preconditions (config + non-empty
		# balanced list + generator present). It is NOT proof the hook ran.
		_ready=false
		if [ "$_cfg" = true ] && [ -s "$BAL_LIST" ] \
			&& grep -qE '^[[:space:]]*[0-9a-fA-F:]' "$BAL_LIST" 2>/dev/null \
			&& [ -x /usr/lib/wan-affinity/gen-dyn-nft.sh ]; then
			_ready=true
		fi
		# Ground truth that steering actually ran: the hook writes field 10
		# (target wan1|wan2) of /tmp/wan-affinity.steer only when its own
		# _bal_active gate passed. Parse defensively - missing/short/garbled
		# state yields null/inactive, never shell arithmetic or bad JSON.
		STEER_STATE=/tmp/wan-affinity.steer
		st_target=""
		if [ -f "$STEER_STATE" ]; then
			st_target=$(awk 'NR==1 && NF>=10 && ($10=="wan1" || $10=="wan2"){print $10}' "$STEER_STATE" 2>/dev/null || true)
		fi
		_act=false
		if [ "$_ready" = true ] && [ -n "$st_target" ]; then
			_act=true
		fi
		if [ -n "$st_target" ]; then
			st_target_json="\"$st_target\""
		else
			st_target_json=null
		fi

		# ---- conntrack bandwidth snapshot (two samples ~1s apart) ---------------
		# For each nf_conntrack line: if ORIGINAL src= is a LAN IP (10.25.x.y),
		# accumulate bytes= values. On each nf_conntrack line, the two bytes= tokens
		# appear in order: first = original direction (upload for LAN src), second =
		# reply direction (download for LAN src). Single awk pass per snapshot.
		_lan_ip=$(uci -q get network.lan.ipaddr 2>/dev/null)
		_lan_mask=$(uci -q get network.lan.netmask 2>/dev/null)
		case "$_lan_mask" in
		    255.255.255.0) LAN_PFX="$(echo "$_lan_ip" | cut -d. -f1-3)." ;;
		    255.255.0.0)   LAN_PFX="$(echo "$_lan_ip" | cut -d. -f1-2)." ;;
		    255.0.0.0)     LAN_PFX="$(echo "$_lan_ip" | cut -d. -f1)." ;;
		    *)             LAN_PFX="$(echo "$_lan_ip" | cut -d. -f1-2)." ;;  # default to /16 (this deployment's mask)
		esac
		[ -n "$_lan_ip" ] || LAN_PFX="10.25."   # fallback when uci unavailable (/16)
		SNAP_A=$(mktemp /tmp/wa_snap_a.XXXXXX)
		SNAP_B=$(mktemp /tmp/wa_snap_b.XXXXXX)

		_snap() {
			awk -v pfx="$LAN_PFX" '
			{
				src=""; b1=0; b2=0; bc=0
				for(i=1;i<=NF;i++){
					fi=$i
					if(src=="" && substr(fi,1,4)=="src="){
						v=substr(fi,5)
						if(substr(v,1,length(pfx))==pfx) src=v
					}
					if(substr(fi,1,6)=="bytes="){
						bc++
						if(bc==1) b1=substr(fi,7)+0
						if(bc==2) b2=substr(fi,7)+0
					}
				}
				if(src!=""){
					up[src]+=b1
					dn[src]+=b2
				}
			}
			END{ for(ip in up) print ip, up[ip], dn[ip] }
			' /proc/net/nf_conntrack 2>/dev/null
		}

		_snap > "$SNAP_A"
		sleep 1
		_snap > "$SNAP_B"

		# Join snapshots by IP; rate_kbps = (B-A)*8/1000 over ~1s; clamp negatives.
		RATES=$(mktemp /tmp/wa_rates.XXXXXX)
		awk '
		NR==FNR{ ua[$1]=$2; da[$1]=$3; next }
		{
			du=$2-ua[$1]+0; dd=$3-da[$1]+0
			if(du<0)du=0
			if(dd<0)dd=0
			printf "%s %d %d\n",$1,int(du*8/1000),int(dd*8/1000)
		}
		' "$SNAP_A" "$SNAP_B" > "$RATES"

		rm -f "$SNAP_A" "$SNAP_B"

		printf '{"meta":{"wan1_label":"%s","wan2_label":"%s","table100_dev":"%s","table101_dev":"%s","capacity":{"wan1_down_mbps":%s,"wan1_up_mbps":%s,"wan2_down_mbps":%s,"wan2_up_mbps":%s,"hi_pct":%s,"lo_pct":%s,"cooldown_s":%s},"steering":{"configured":%s,"active":%s,"target":%s}},"devices":[' \
			"$w1l" "$w2l" "$t100e" "$t101e" \
			"$(_jnum "$mc_w1d")" "$(_jnum "$mc_w1u")" "$(_jnum "$mc_w2d")" "$(_jnum "$mc_w2u")" \
			"$(_jnum "$mc_hi")" "$(_jnum "$mc_lo")" "$(_jnum "$mc_cd")" \
			"$_cfg" "$_act" "$st_target_json"

		sep=""
		seen=" "

		# devices from dhcp leases
		if [ -f "$LEASES" ]; then
			while read -r _exp mac ip name _cid; do
				[ -z "$mac" ] && continue
				m=$(printf '%s' "$mac" | tr 'A-F' 'a-f')
				case "$seen" in *" $m "*) continue ;; esac
				seen="$seen$m "

				# balanced checked FIRST so a static pin overwrites it: at runtime the
				# static chain runs before the dyn chain and wins overlaps, so report
				# the effective result even for manually-corrupted overlapping lists.
				wan="default"
				in_list "$m" "$BAL_LIST"   && wan="balanced"
				in_list "$m" "$VIVO_LIST"  && wan="wan1"
				in_list "$m" "$CLARO_LIST" && wan="wan2"

				online_val="false"
				[ "$ip" != "-" ] && is_online "$ip" && online_val="true"

				# Name resolution priority: custom > dhcp (skip "*" "-") > empty
				custom=$(cname "$m")
				if [ -n "$custom" ]; then
					resolved="$custom"
				elif [ "$name" != "*" ] && [ "$name" != "-" ] && [ -n "$name" ]; then
					resolved="$name"
				else
					resolved=""
				fi

				# Vendor only for nameless devices (skip awk startup cost for named ones)
				vendor=""
				[ -z "$resolved" ] && vendor=$(oui_vendor "$m")

				# Rates: look up by IP in RATES file
				up_kbps=0
				dn_kbps=0
				if [ "$ip" != "-" ] && [ -f "$RATES" ]; then
					_rate=$(awk -v ip="$ip" '$1==ip{print $2,$3; exit}' "$RATES")
					if [ -n "$_rate" ]; then
						up_kbps=${_rate%% *}
						dn_kbps=${_rate##* }
					fi
				fi

				jm=$(jsonesc "$m")
				ji=$(jsonesc "$ip")
				jn=$(jsonesc "$resolved")
				jv=$(jsonesc "$vendor")
				jc=$(jsonesc "$custom")

				printf '%s{"mac":"%s","ip":"%s","name":"%s","vendor":"%s","custom_name":"%s","online":%s,"wan":"%s","up_kbps":%s,"down_kbps":%s}' \
					"$sep" "$jm" "$ji" "$jn" "$jv" "$jc" "$online_val" "$wan" "$up_kbps" "$dn_kbps"
				sep=","
			done < "$LEASES"
		fi

		# locked/balanced-but-offline devices not in current leases
		for lf in "$VIVO_LIST" "$CLARO_LIST" "$BAL_LIST"; do
			[ -f "$lf" ] || continue
			while IFS= read -r line; do
				m=$(echo "$line" | sed 's/#.*//; s/[[:space:]]//g' | tr 'A-F' 'a-f')
				[ -z "$m" ] && continue
				case "$seen" in *" $m "*) continue ;; esac
				seen="$seen$m "

				# balanced checked FIRST so a static pin overwrites it: at runtime the
				# static chain runs before the dyn chain and wins overlaps, so report
				# the effective result even for manually-corrupted overlapping lists.
				wan="default"
				in_list "$m" "$BAL_LIST"   && wan="balanced"
				in_list "$m" "$VIVO_LIST"  && wan="wan1"
				in_list "$m" "$CLARO_LIST" && wan="wan2"

				custom=$(cname "$m")
				resolved="$custom"
				vendor=""
				[ -z "$resolved" ] && vendor=$(oui_vendor "$m")

				jm=$(jsonesc "$m")
				jn=$(jsonesc "$resolved")
				jv=$(jsonesc "$vendor")
				jc=$(jsonesc "$custom")

				printf '%s{"mac":"%s","ip":"-","name":"%s","vendor":"%s","custom_name":"%s","online":false,"wan":"%s","up_kbps":0,"down_kbps":0}' \
					"$sep" "$jm" "$jn" "$jv" "$jc" "$wan"
				sep=","
			done < "$lf"
		done

		rm -f "$RATES"

		printf ']}'
		exit 0
		;;
esac

# ---- MODE 1: GET (no api) -> HTML shell ----------------------------------------
printf 'Content-Type: text/html; charset=utf-8\r\n\r\n'

# Escape labels for embedding in JS string literals (single-quoted in the heredoc).
# Labels come from uci (trusted admin config), but escape anyway for correctness.
w1l_js=$(printf '%s' "$wan1_label" | sed "s/\\\\/\\\\\\\\/g; s/'/\\\\'/g")
w2l_js=$(printf '%s' "$wan2_label" | sed "s/\\\\/\\\\\\\\/g; s/'/\\\\'/g")

cat <<HTMLHEAD
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NexusGate - WAN Affinity</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1020;color:#e6ecff}
.wrap{max-width:960px;margin:0 auto;padding:18px 16px}
/* ---- header bar ---- */
.hdr{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 4px}
h1{font-size:19px;margin:0;flex:1 1 auto}
.hdr-right{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.count-summary{color:#8b96b8;font-size:13px}
.count-summary b{color:#e6ecff}
/* ---- toolbar ---- */
.toolbar{display:flex;gap:8px;align-items:center;margin:12px 0;flex-wrap:wrap;position:sticky;top:0;z-index:5;background:#0b1020;padding:10px 0;box-shadow:0 6px 12px -8px rgba(0,0,0,.8)}
.toolbar input[type=search]{background:#0b1020;color:#e6ecff;border:1px solid #232c4d;border-radius:6px;padding:7px 10px;font-size:13px;width:220px;flex:1 1 160px;max-width:320px}
.toolbar input[type=search]::placeholder{color:#4a5578}
.live-label{font-size:13px;color:#8b96b8;display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none}
.live-label input{cursor:pointer}
/* ---- accessible focus ---- */
button:focus-visible,input:focus-visible,select:focus-visible,label:focus-within,.th-btn:focus-visible{outline:2px solid #4da3ff;outline-offset:1px}
.seg label:focus-visible{outline-offset:-2px}
/* ---- meta line ---- */
.meta{color:#8b96b8;font-size:13px;margin:0 0 12px}
.meta b{color:#e6ecff}
/* ---- toast ---- */
.toast{padding:10px 14px;border-radius:8px;margin:0 0 14px;font-size:14px;display:none}
.toast.ok{background:#10301a;border:1px solid #1f6f37;color:#3ddc84;display:block}
.toast.err{background:#3a1414;border:1px solid #8b2a2a;color:#ff5470;display:block}
/* ---- table ---- */
table{width:100%;border-collapse:collapse;background:#141b31;border-radius:10px;overflow:hidden}
th,td{padding:9px 10px;text-align:left;border-bottom:1px solid #232c4d;font-size:14px;vertical-align:middle}
th{background:#182038;color:#8b96b8;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.4px;user-select:none;white-space:nowrap;padding:0}
th:last-child{padding:9px 10px}
.th-btn{display:block;width:100%;background:none;border:0;color:inherit;font:inherit;text-transform:inherit;letter-spacing:inherit;text-align:left;padding:9px 10px;cursor:pointer;border-radius:0}
.th-btn:hover{color:#e6ecff}
th .sort-arrow{font-size:10px;opacity:.5;margin-left:3px}
th.active-sort .sort-arrow{opacity:1;color:#4da3ff}
tr:last-child td{border-bottom:none}
tr.hidden-row{display:none}
.mac{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;color:#c9d1d9}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;flex-shrink:0}
.dot-on{background:#3fb950;box-shadow:0 0 0 2px #10301a}
.dot-off{background:#4a5578}
/* row accent by WAN assignment */
.r-wan1 td:first-child{border-left:3px solid #4da3ff}
.r-wan2 td:first-child{border-left:3px solid #d2a8ff}
.r-default td:first-child{border-left:3px solid transparent}
/* ---- segmented WAN control ---- */
.seg{display:inline-flex;border:1px solid #232c4d;border-radius:6px;overflow:hidden;font-size:12px}
.seg label{padding:5px 9px;cursor:pointer;color:#8b96b8;white-space:nowrap;transition:background .12s,color .12s}
.seg input[type=radio]{display:none}
.seg input:checked + label.lbl-default{background:#1f3a1f;color:#3ddc84}
.seg input:checked + label.lbl-wan1{background:#132a45;color:#4da3ff}
.seg input:checked + label.lbl-wan2{background:#2c1f45;color:#d2a8ff}
.seg input:checked + label.lbl-balanced{background:#3a2f14;color:#e3b341}
.seg label:hover{background:#232c4d;color:#e6ecff}
/* ---- buttons ---- */
button{border:0;border-radius:8px;padding:8px 16px;font-size:14px;font-weight:600;cursor:pointer;transition:background .12s}
.btn-save{background:#238636;color:#fff}
.btn-save:hover{background:#2ea043}
.btn-save:disabled{background:#141b31;color:#4a5578;cursor:not-allowed;border:1px solid #232c4d}
.btn-refresh{background:#232c4d;color:#c9d1d9;border:1px solid #232c4d}
.btn-refresh:hover{background:#2d333b}
.btn-refresh:disabled{opacity:.5;cursor:not-allowed}
/* ---- spinner ---- */
.spin{display:inline-block;width:14px;height:14px;border:2px solid #4a5578;border-top-color:#4da3ff;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:4px}
@keyframes spin{to{transform:rotate(360deg)}}
/* ---- dirty badge ---- */
.dirty-badge{font-size:12px;color:#e3b341;background:#2d2207;border:1px solid #6a4a0a;border-radius:6px;padding:3px 8px;display:none}
.dirty-badge.show{display:inline-block}
/* ---- name cell ---- */
.name-wrap{display:flex;align-items:center;gap:5px;min-width:0}
.name-edit-btn{background:none;border:none;padding:1px 4px;font-size:13px;color:#4a5578;cursor:pointer;border-radius:4px;line-height:1;flex-shrink:0}
.name-edit-btn:hover{color:#8b96b8;background:#232c4d}
.name-vendor{color:#8b96b8;font-style:italic;font-size:13px}
.name-input{background:#0b1020;color:#e6ecff;border:1px solid #4da3ff;border-radius:5px;padding:3px 6px;font-size:13px;min-width:80px;width:160px}
/* ---- rate columns ---- */
td.rate{font-variant-numeric:tabular-nums;font-size:13px;color:#8b96b8;text-align:right;white-space:nowrap}
td.rate.active{color:#e6ecff}
.rate-muted{color:#4a5578}
/* ---- add-device panel ---- */
.add-panel{margin-top:18px;padding:14px;background:#141b31;border:1px solid #232c4d;border-radius:10px}
.add-panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.4px;color:#8b96b8;margin:0 0 10px}
.add-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.add-panel input[type=text]{background:#0b1020;color:#e6ecff;border:1px solid #232c4d;border-radius:6px;padding:7px 9px;font-family:ui-monospace,monospace;font-size:13px;width:210px}
.add-panel select{background:#0b1020;color:#e6ecff;border:1px solid #232c4d;border-radius:6px;padding:6px 8px;font-size:13px}
.btn-add{background:#232c4d;color:#c9d1d9;border:1px solid #232c4d;padding:7px 14px;font-size:13px}
.btn-add:hover{background:#2d333b}
/* ---- empty state ---- */
.empty-row td{color:#8b96b8;text-align:center;padding:28px 10px;font-style:italic}
/* ---- capacity panel + steering pill ---- */
.cap-panel{background:#141b31;border:1px solid #232c4d;border-radius:10px;padding:14px 16px;margin-top:16px}
.cap-panel h2{margin:0 0 4px;font-size:15px}
.cap-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:10px 0}
.cap-grid label{display:block;font-size:11px;color:#8b96b8;text-transform:uppercase;letter-spacing:.4px;margin-bottom:3px}
.cap-grid input{width:100%;box-sizing:border-box;background:#0b1020;border:1px solid #232c4d;border-radius:6px;color:#e6ecff;padding:7px 9px;font-size:14px}
.btn-cap{background:#238636;color:#fff}
.btn-cap:disabled{background:#1c2440;color:#8b96b8;cursor:default}
.steer-pill{display:inline-block;font-size:11px;font-weight:700;border-radius:999px;padding:3px 10px;letter-spacing:.3px;margin-left:8px;vertical-align:1px}
.steer-off{background:#1c2440;color:#8b96b8}
.steer-on{background:#3a2f14;color:#e3b341}
/* ---- legend ---- */
.legend{color:#8b96b8;font-size:12px;margin-top:10px}
/* ---- WAN assignment badge (card mode) ---- */
.wan-badge{display:none;font-size:11px;font-weight:700;border-radius:5px;padding:2px 7px;letter-spacing:.3px}
.r-wan1 .wan-badge{background:#132a45;color:#4da3ff}
.r-wan2 .wan-badge{background:#2c1f45;color:#d2a8ff}
.r-default .wan-badge{background:#1f3a1f;color:#3ddc84}
.r-balanced .wan-badge{background:#3a2f14;color:#e3b341}
/* ---- narrow screens: cards, not a horizontal-scroll table ---- */
@media(max-width:720px){
  table,tbody{display:block}
  thead{display:none}
  tbody tr{display:grid;grid-template-columns:auto 1fr auto;gap:2px 10px;align-items:center;background:#141b31;border:1px solid #232c4d;border-radius:10px;padding:10px 12px;margin-bottom:10px}
  tbody tr.hidden-row{display:none}
  td{display:block;border-bottom:none;padding:1px 0;font-size:13px}
  td[data-label]::before{content:attr(data-label);color:#8b96b8;font-size:10px;text-transform:uppercase;letter-spacing:.4px;display:block}
  td:first-child{grid-column:1;grid-row:1}
  td:nth-child(2){grid-column:2;grid-row:1;font-weight:600;font-size:14px}
  td:nth-child(2)::before,td:first-child::before{display:none}
  td:nth-child(3){grid-column:2/4;grid-row:2}
  td:nth-child(4){grid-column:2/4;grid-row:3}
  td.rate{grid-row:4;text-align:left}
  td.rate.col-down{grid-column:2}
  td.rate.col-up{grid-column:3}
  td:last-child{grid-column:1/-1;grid-row:5;display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px 0 0;border-top:1px solid #232c4d;margin-top:6px}
  .wan-badge{display:inline-block}
  .r-wan1 td:first-child,.r-wan2 td:first-child,.r-default td:first-child{border-left:none}
  tbody tr.r-wan1{border-left:3px solid #4da3ff}
  tbody tr.r-wan2{border-left:3px solid #d2a8ff}
  tbody tr.r-balanced{border-left:3px solid #e3b341}
  .empty-row{display:block}
  .empty-row td{grid-column:1/-1}
  .seg label{padding:6px 8px;font-size:12px}
  .toolbar input[type=search]{max-width:none}
}
</style>
</head>
<body>
<div class="wrap">

<div class="hdr">
  <h1>WAN Affinity</h1>
  <div class="hdr-right">
    <span class="count-summary" id="count-summary"></span>
    <button class="btn-refresh" id="btn-refresh" onclick="refreshDevices()">Refresh</button>
  </div>
</div>
<p class="meta" id="meta-line">Loading&hellip;</p>

<div class="toast" id="toast"></div>

<div class="toolbar">
  <input type="search" id="search" placeholder="Filter by IP, MAC or name&hellip;" oninput="filterRows()" autocomplete="off" autocapitalize="off" spellcheck="false">
  <span class="dirty-badge" id="dirty-badge"></span>
  <button class="btn-save" id="btn-save" disabled onclick="saveChanges()">Save &amp; apply</button>
  <label class="live-label" title="Auto-refresh every 3 seconds (each refresh takes ~1s for rate sampling)">
    <input type="checkbox" id="live-chk" onchange="toggleLive()"> Live
  </label>
</div>

<table id="dev-table">
  <thead>
    <tr>
      <th id="th-online"><button type="button" class="th-btn" onclick="sortBy('online')" aria-label="Sort by online status"><span class="sort-arrow">&#9660;</span></button></th>
      <th id="th-ip"><button type="button" class="th-btn" onclick="sortBy('ip')">IP <span class="sort-arrow" aria-hidden="true"></span></button></th>
      <th id="th-mac"><button type="button" class="th-btn" onclick="sortBy('mac')">MAC <span class="sort-arrow" aria-hidden="true"></span></button></th>
      <th id="th-name"><button type="button" class="th-btn" onclick="sortBy('name')">Name <span class="sort-arrow" aria-hidden="true"></span></button></th>
      <th id="th-down" class="col-down"><button type="button" class="th-btn" onclick="sortBy('down_kbps')">&#8595; Down <span class="sort-arrow" aria-hidden="true"></span></button></th>
      <th id="th-up" class="col-up"><button type="button" class="th-btn" onclick="sortBy('up_kbps')">&#8593; Up <span class="sort-arrow" aria-hidden="true"></span></button></th>
      <th>WAN</th>
    </tr>
  </thead>
  <tbody id="dev-body">
    <tr><td colspan="7" style="text-align:center;padding:20px;color:#8b96b8">Loading&hellip;</td></tr>
  </tbody>
</table>

<div class="add-panel">
  <h2>Add a device by MAC</h2>
  <div class="add-row">
    <input type="text" id="add-mac" placeholder="aa:bb:cc:dd:ee:ff" autocomplete="off" autocapitalize="off" spellcheck="false">
    <select id="add-wan">
      <option value="c" id="add-opt-wan2"></option>
      <option value="v" id="add-opt-wan1"></option>
      <option value="b">Auto (balanced)</option>
      <option value="d">Default</option>
    </select>
    <button class="btn-add" onclick="addDevice()">Add</button>
  </div>
  <p class="legend">For a device that has not yet requested DHCP. It will appear in the table and be included in the next Save.</p>
</div>

<div class="cap-panel">
  <h2>WAN capacity &amp; Auto (balanced) steering<span class="steer-pill steer-off" id="steer-pill">steering off</span></h2>
  <p class="legend">Auto devices spill over between WANs based on load. Steering stays OFF until real down/up Mbps are saved for BOTH WANs - guessed capacities could steer traffic into a saturated link.</p>
  <div class="cap-grid">
    <div><label for="cap-w1d" id="cap-w1d-lbl">WAN1 down Mbps</label><input id="cap-w1d" inputmode="numeric" autocomplete="off"></div>
    <div><label for="cap-w1u" id="cap-w1u-lbl">WAN1 up Mbps</label><input id="cap-w1u" inputmode="numeric" autocomplete="off"></div>
    <div><label for="cap-w2d" id="cap-w2d-lbl">WAN2 down Mbps</label><input id="cap-w2d" inputmode="numeric" autocomplete="off"></div>
    <div><label for="cap-w2u" id="cap-w2u-lbl">WAN2 up Mbps</label><input id="cap-w2u" inputmode="numeric" autocomplete="off"></div>
    <div><label for="cap-hi">High threshold %</label><input id="cap-hi" inputmode="numeric" autocomplete="off" placeholder="85"></div>
    <div><label for="cap-lo">Low threshold %</label><input id="cap-lo" inputmode="numeric" autocomplete="off" placeholder="60"></div>
    <div><label for="cap-cd">Cooldown s</label><input id="cap-cd" inputmode="numeric" autocomplete="off" placeholder="120"></div>
  </div>
  <button class="btn-cap" id="btn-cap" onclick="saveCapacity()">Save capacity</button>
</div>

<p class="legend">
  Green dot = currently reachable (REACHABLE/STALE/DELAY/PROBE in ARP table).
  &ldquo;Default&rdquo; = unlocked device follows the default WAN.
  Locking pins the device to one WAN with automatic failover.
  &ldquo;Auto&rdquo; adds the device to the balanced spillover pool (steered by load once capacities are configured).
  Click &#9998; to rename a device (stored in /etc/wan-affinity/names.list, survives reboots).
  Italic muted text = offline OUI vendor lookup (no custom name set).
  Rates from conntrack; each refresh takes ~1s. Enable Live for continuous updates.
</p>

</div><!-- .wrap -->
<script>
// Provider labels injected server-side (provider-agnostic; no Vivo/Claro hardcoded in UI)
var WAN1_LABEL = '$w1l_js';
var WAN2_LABEL = '$w2l_js';

// ---- state ------------------------------------------------------------------
// devices: [{mac,ip,name,vendor,custom_name,online,wan,up_kbps,down_kbps}, ...]
var devices = [];
var overrides = {};     // {mac -> wan} for user-edited rows (dirty state)
var sortKey = 'online'; // default: online-first
var sortAsc = true;
var liveTimer = null;

// ---- init -------------------------------------------------------------------
document.getElementById('add-opt-wan2').textContent = WAN2_LABEL + ' (locked)';
document.getElementById('add-opt-wan1').textContent = WAN1_LABEL + ' (locked)';
document.getElementById('add-opt-wan2').value = 'c';
document.getElementById('add-opt-wan1').value = 'v';
refreshDevices();

// ---- live toggle ------------------------------------------------------------
function toggleLive() {
  var chk = document.getElementById('live-chk');
  if (chk.checked) {
    liveTimer = setInterval(refreshDevices, 3000);
  } else {
    if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  }
}

// ---- fetch device list ------------------------------------------------------
function refreshDevices() {
  var btn = document.getElementById('btn-refresh');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span>Refreshing';
  fetch('?api=devices')
    .then(function(r){ return r.json(); })
    .then(function(data){
      devices = data.devices || [];
      overrides = {};
      updateMeta(data.meta || {});
      renderTable();
      updateDirty();
      showToast('', '');  // clear any previous toast
    })
    .catch(function(e){
      showToast('Refresh failed: ' + e.message, 'err');
    })
    .finally(function(){
      btn.disabled = false;
      btn.textContent = 'Refresh';
    });
}

// ---- meta line --------------------------------------------------------------
function updateMeta(meta) {
  var w1 = meta.wan1_label || WAN1_LABEL;
  var w2 = meta.wan2_label || WAN2_LABEL;
  var d1 = meta.table100_dev || '(down)';
  var d2 = meta.table101_dev || '(down)';
  var el = document.getElementById('meta-line');
  el.innerHTML = '';
  var t = document.createTextNode(w1 + ' (table 100) via ');
  var b1 = document.createElement('b'); b1.textContent = d1;
  var mid = document.createTextNode(' · ' + w2 + ' (table 101) via ');
  var b2 = document.createElement('b'); b2.textContent = d2;
  el.appendChild(t); el.appendChild(b1); el.appendChild(mid); el.appendChild(b2);

  // capacity labels follow provider labels
  var l1d=document.getElementById('cap-w1d-lbl'), l1u=document.getElementById('cap-w1u-lbl');
  var l2d=document.getElementById('cap-w2d-lbl'), l2u=document.getElementById('cap-w2u-lbl');
  if (l1d) l1d.textContent = w1 + ' down Mbps';
  if (l1u) l1u.textContent = w1 + ' up Mbps';
  if (l2d) l2d.textContent = w2 + ' down Mbps';
  if (l2u) l2u.textContent = w2 + ' up Mbps';

  // fill capacity inputs from meta, but never clobber in-progress edits
  var cap = meta.capacity || {};
  var fields = [['cap-w1d','wan1_down_mbps'],['cap-w1u','wan1_up_mbps'],
                ['cap-w2d','wan2_down_mbps'],['cap-w2u','wan2_up_mbps'],
                ['cap-hi','hi_pct'],['cap-lo','lo_pct'],['cap-cd','cooldown_s']];
  for (var i = 0; i < fields.length; i++) {
    var inp = document.getElementById(fields[i][0]);
    if (!inp || inp === document.activeElement || inp.dataset.dirty === '1') continue;
    var v = cap[fields[i][1]];
    inp.value = (v === null || v === undefined) ? '' : String(v);
  }

  // steering pill
  var st = meta.steering || {};
  var pill = document.getElementById('steer-pill');
  if (pill) {
    if (st.active) {
      pill.className = 'steer-pill steer-on';
      var tl = st.target === 'wan1' ? w1 : st.target === 'wan2' ? w2 : null;
      pill.textContent = tl ? ('steering: new Auto flows -> ' + tl) : 'steering active';
    } else if (st.configured) {
      pill.className = 'steer-pill steer-off';
      pill.textContent = 'configured - no Auto devices';
    } else {
      pill.className = 'steer-pill steer-off';
      pill.textContent = 'steering off - set capacities';
    }
  }
}

// ---- capacity save ----------------------------------------------------------
// Marks inputs dirty on edit so live refresh never clobbers typing; clears the
// flags after a successful save so the server-confirmed values show again.
(function(){
  var ids = ['cap-w1d','cap-w1u','cap-w2d','cap-w2u','cap-hi','cap-lo','cap-cd'];
  for (var i = 0; i < ids.length; i++) {
    var el = document.getElementById(ids[i]);
    if (el) el.addEventListener('input', function(){ this.dataset.dirty = '1'; });
  }
})();

function saveCapacity() {
  var get = function(id){ return document.getElementById(id).value.trim(); };
  var vals = {
    wan1_down_mbps: get('cap-w1d'), wan1_up_mbps: get('cap-w1u'),
    wan2_down_mbps: get('cap-w2d'), wan2_up_mbps: get('cap-w2u'),
    hi_pct: get('cap-hi') || '85', lo_pct: get('cap-lo') || '60',
    cooldown_s: get('cap-cd') || '120'
  };
  // client-side mirror of server validation for fast feedback
  var pos = /^[0-9]+$/;
  var k;
  for (k in vals) {
    if (!pos.test(vals[k])) { showToast('All capacity fields must be numbers (' + k + ').', 'err'); return; }
  }
  if (+vals.wan1_down_mbps < 1 || +vals.wan1_up_mbps < 1 || +vals.wan2_down_mbps < 1 || +vals.wan2_up_mbps < 1) {
    showToast('Capacities must be positive Mbps.', 'err'); return;
  }
  var hi = +vals.hi_pct, lo = +vals.lo_pct;
  if (!(lo > 0 && lo < hi && hi <= 100)) {
    showToast('Need 0 < low < high <= 100.', 'err'); return;
  }
  var btn = document.getElementById('btn-cap');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span>Saving';
  var body = 'action=capacity';
  for (k in vals) body += '&' + k + '=' + encodeURIComponent(vals[k]);
  fetch(window.location.pathname, {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: body
  })
    .then(function(r){ return r.json(); })
    .then(function(res){
      if (res.ok) {
        showToast(res.msg || 'Capacity saved.', 'ok');
        var ids = ['cap-w1d','cap-w1u','cap-w2d','cap-w2u','cap-hi','cap-lo','cap-cd'];
        for (var i = 0; i < ids.length; i++) {
          var el = document.getElementById(ids[i]);
          if (el) delete el.dataset.dirty;
        }
        refreshDevices();  // re-pull meta so the steering pill reflects the new state
      } else {
        showToast(res.msg || 'Capacity save failed.', 'err');
      }
    })
    .catch(function(e){ showToast('Capacity save failed: ' + e.message, 'err'); })
    .finally(function(){
      btn.disabled = false;
      btn.textContent = 'Save capacity';
    });
}

// ---- sort -------------------------------------------------------------------
function sortBy(key) {
  if (sortKey === key) { sortAsc = !sortAsc; }
  else { sortKey = key; sortAsc = (key !== 'online'); }
  updateSortHeaders();
  renderTable();
}

function updateSortHeaders() {
  var cols = ['online','ip','mac','name','down_kbps','up_kbps'];
  var ids  = ['online','ip','mac','name','down',     'up'     ];
  for (var i = 0; i < cols.length; i++) {
    var th = document.getElementById('th-' + ids[i]);
    if (!th) continue;
    var arrow = th.querySelector('.sort-arrow');
    if (cols[i] === sortKey) {
      th.classList.add('active-sort');
      if (arrow) arrow.innerHTML = sortAsc ? '&#9650;' : '&#9660;';
    } else {
      th.classList.remove('active-sort');
      if (arrow) arrow.innerHTML = '';
    }
  }
}

function compareRows(a, b) {
  var av, bv, c;
  if (sortKey === 'online') {
    if (a.online !== b.online) return a.online ? -1 : 1;
    return (a.name || a.ip || '').localeCompare(b.name || b.ip || '');
  }
  if (sortKey === 'ip') {
    av = ipToNum(a.ip); bv = ipToNum(b.ip);
    return sortAsc ? av - bv : bv - av;
  }
  if (sortKey === 'down_kbps') {
    av = a.down_kbps || 0; bv = b.down_kbps || 0;
    return sortAsc ? av - bv : bv - av;
  }
  if (sortKey === 'up_kbps') {
    av = a.up_kbps || 0; bv = b.up_kbps || 0;
    return sortAsc ? av - bv : bv - av;
  }
  if (sortKey === 'mac') { av = a.mac; bv = b.mac; }
  else { av = a.name || a.ip || ''; bv = b.name || b.ip || ''; }
  c = av.localeCompare(bv);
  return sortAsc ? c : -c;
}

function ipToNum(ip) {
  if (!ip || ip === '-') return 0;
  var parts = ip.split('.');
  return ((parseInt(parts[0],10)||0)*16777216 + (parseInt(parts[1],10)||0)*65536 +
          (parseInt(parts[2],10)||0)*256 + (parseInt(parts[3],10)||0));
}

// format kbps -> display string; null means zero (caller shows muted dot)
function fmtRate(kbps) {
  if (!kbps || kbps <= 0) return null;
  if (kbps < 1000) return kbps + ' kb/s';
  return (kbps / 1000).toFixed(1) + ' Mb/s';
}

// ---- render -----------------------------------------------------------------
function renderTable() {
  var sorted = devices.slice().sort(compareRows);
  var tbody = document.getElementById('dev-body');
  tbody.innerHTML = '';

  if (sorted.length === 0) {
    var etr = document.createElement('tr');
    etr.className = 'empty-row';
    var etd = document.createElement('td');
    etd.colSpan = 7;
    etd.textContent = 'No devices found - is anything connected?';
    etr.appendChild(etd);
    tbody.appendChild(etr);
    updateSummary(0, 0, 0, 0, 0);
    return;
  }

  var filter = document.getElementById('search').value.toLowerCase();
  var total = sorted.length, nDef = 0, nW1 = 0, nW2 = 0, nBal = 0;

  for (var i = 0; i < sorted.length; i++) {
    var d = sorted[i];
    var curWan = overrides[d.mac] !== undefined ? overrides[d.mac] : d.wan;
    if (curWan === 'wan1') nW1++;
    else if (curWan === 'wan2') nW2++;
    else if (curWan === 'balanced') nBal++;
    else nDef++;

    var tr = document.createElement('tr');
    tr.dataset.mac = d.mac;
    tr.className = 'r-' + curWan;

    // hide if filter doesn't match
    if (filter) {
      var haystack = ((d.ip||'') + ' ' + d.mac + ' ' + (d.name||'') + ' ' + (d.vendor||'')).toLowerCase();
      if (haystack.indexOf(filter) === -1) tr.classList.add('hidden-row');
    }

    // col: online dot
    var tdDot = document.createElement('td');
    tdDot.setAttribute('data-label', '');
    var dot = document.createElement('span');
    dot.className = 'dot dot-' + (d.online ? 'on' : 'off');
    dot.title = d.online ? 'online' : 'offline';
    tdDot.appendChild(dot);
    tr.appendChild(tdDot);

    // col: ip
    var tdIp = document.createElement('td');
    tdIp.setAttribute('data-label', 'IP');
    tdIp.textContent = d.ip === '-' ? '' : d.ip;
    tr.appendChild(tdIp);

    // col: mac
    var tdMac = document.createElement('td');
    tdMac.setAttribute('data-label', 'MAC');
    tdMac.className = 'mac';
    tdMac.textContent = d.mac;
    tr.appendChild(tdMac);

    // col: name (with inline edit)
    var tdName = document.createElement('td');
    tdName.setAttribute('data-label', 'Name');
    tdName.appendChild(makeNameCell(d));
    tr.appendChild(tdName);

    // col: down rate
    var tdDown = document.createElement('td');
    tdDown.setAttribute('data-label', 'Down');
    tdDown.className = 'rate col-down';
    var dnStr = fmtRate(d.down_kbps);
    if (dnStr) {
      tdDown.textContent = dnStr;
      tdDown.classList.add('active');
    } else {
      var sp1 = document.createElement('span');
      sp1.className = 'rate-muted'; sp1.textContent = '·';
      tdDown.appendChild(sp1);
    }
    tr.appendChild(tdDown);

    // col: up rate
    var tdUp = document.createElement('td');
    tdUp.setAttribute('data-label', 'Up');
    tdUp.className = 'rate col-up';
    var upStr = fmtRate(d.up_kbps);
    if (upStr) {
      tdUp.textContent = upStr;
      tdUp.classList.add('active');
    } else {
      var sp2 = document.createElement('span');
      sp2.className = 'rate-muted'; sp2.textContent = '·';
      tdUp.appendChild(sp2);
    }
    tr.appendChild(tdUp);

    // col: WAN segmented control
    var tdWan = document.createElement('td');
    tdWan.appendChild(makeSegControl(d.mac, curWan));
    var badge = document.createElement('span');
    badge.className = 'wan-badge';
    badge.textContent = curWan === 'wan1' ? WAN1_LABEL : curWan === 'wan2' ? WAN2_LABEL : curWan === 'balanced' ? 'Auto' : 'Default';
    tdWan.appendChild(badge);
    tr.appendChild(tdWan);

    tbody.appendChild(tr);
  }

  updateSummary(total, nDef, nW1, nW2, nBal);
  updateSortHeaders();
}

// ---- name cell: display name or vendor, pencil edit button ------------------
function makeNameCell(d) {
  var wrap = document.createElement('div');
  wrap.className = 'name-wrap';

  var nameSpan = document.createElement('span');
  if (d.name) {
    nameSpan.textContent = d.name; // resolved name (custom or dhcp); textContent = XSS-safe
  } else if (d.vendor) {
    nameSpan.className = 'name-vendor';
    nameSpan.textContent = '~ ' + d.vendor; // OUI vendor, muted italic
  }
  wrap.appendChild(nameSpan);

  var editBtn = document.createElement('button');
  editBtn.className = 'name-edit-btn';
  editBtn.textContent = '✎'; // pencil
  editBtn.title = 'Rename device';
  editBtn.type = 'button';
  // capture d by value via IIFE to avoid closure-over-loop-variable issue
  (function(dev) {
    editBtn.addEventListener('click', function() {
      startNameEdit(dev, wrap, nameSpan, editBtn);
    });
  })(d);
  wrap.appendChild(editBtn);

  return wrap;
}

function startNameEdit(d, wrap, nameSpan, editBtn) {
  nameSpan.style.display = 'none';
  editBtn.style.display = 'none';

  var inp = document.createElement('input');
  inp.type = 'text';
  inp.className = 'name-input';
  inp.value = d.custom_name || '';
  inp.maxLength = 48;
  inp.placeholder = 'Device name (empty = clear)';
  wrap.insertBefore(inp, editBtn);
  inp.focus();
  inp.select();

  var committed = false;

  function commitEdit() {
    if (committed) return;
    committed = true;
    inp.disabled = true;
    fetch(window.location.pathname, {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'action=rename&mac=' + encodeURIComponent(d.mac) + '&name=' + encodeURIComponent(inp.value)
    })
      .then(function(r){ return r.json(); })
      .then(function(res){
        if (res.ok) {
          refreshDevices();
        } else {
          showToast(res.msg || 'Rename failed.', 'err');
          cancelEdit();
        }
      })
      .catch(function(e){
        showToast('Rename failed: ' + e.message, 'err');
        cancelEdit();
      });
  }

  function cancelEdit() {
    committed = true;
    if (inp.parentNode) inp.parentNode.removeChild(inp);
    nameSpan.style.display = '';
    editBtn.style.display = '';
  }

  inp.addEventListener('keydown', function(e) {
    if (e.key === 'Enter')  { e.preventDefault(); commitEdit(); }
    if (e.key === 'Escape') { e.preventDefault(); cancelEdit(); }
  });
  // blur: commit after short delay so Escape keydown fires first
  inp.addEventListener('blur', function() {
    setTimeout(function(){ commitEdit(); }, 120);
  });
}

function makeSegControl(mac, curWan) {
  var seg = document.createElement('div');
  seg.className = 'seg';
  var nm = 'w_' + mac.replace(/:/g, '');

  var opts = [
    {val:'default',  label:'Default',   cls:'lbl-default'},
    {val:'wan1',     label:WAN1_LABEL,  cls:'lbl-wan1'},
    {val:'wan2',     label:WAN2_LABEL,  cls:'lbl-wan2'},
    {val:'balanced', label:'Auto',      cls:'lbl-balanced'}
  ];

  for (var i = 0; i < opts.length; i++) {
    var o = opts[i];
    var inp = document.createElement('input');
    inp.type = 'radio';
    inp.name = nm;
    inp.id = nm + '_' + o.val;
    inp.value = o.val;
    inp.checked = (curWan === o.val);
    inp.dataset.mac = mac;
    inp.addEventListener('change', onWanChange);

    var lbl = document.createElement('label');
    lbl.htmlFor = nm + '_' + o.val;
    lbl.className = o.cls;
    lbl.textContent = o.label;

    seg.appendChild(inp);
    seg.appendChild(lbl);
  }
  return seg;
}

// ---- change tracking --------------------------------------------------------
function onWanChange(e) {
  var mac = e.target.dataset.mac;
  var newWan = e.target.value;
  var orig = 'default';
  for (var i = 0; i < devices.length; i++) {
    if (devices[i].mac === mac) { orig = devices[i].wan; break; }
  }
  if (newWan === orig) {
    delete overrides[mac];
  } else {
    overrides[mac] = newWan;
  }
  var tr = document.querySelector('tr[data-mac="' + mac + '"]');
  if (tr) { tr.className = 'r-' + newWan; }
  updateDirty();
}

function updateDirty() {
  var n = Object.keys(overrides).length;
  var badge = document.getElementById('dirty-badge');
  var saveBtn = document.getElementById('btn-save');
  if (n > 0) {
    badge.textContent = n + ' pending change' + (n > 1 ? 's' : '');
    badge.classList.add('show');
    saveBtn.disabled = false;
  } else {
    badge.classList.remove('show');
    saveBtn.disabled = true;
  }
}

// ---- save -------------------------------------------------------------------
function saveChanges() {
  var saveBtn = document.getElementById('btn-save');
  saveBtn.disabled = true;
  saveBtn.innerHTML = '<span class="spin"></span>Saving';

  // Build pairs payload: for every device, emit its current (overridden or original) wan
  var tokens = [];
  for (var i = 0; i < devices.length; i++) {
    var d = devices[i];
    var wan = overrides[d.mac] !== undefined ? overrides[d.mac] : d.wan;
    var w = wan === 'wan1' ? 'v' : wan === 'wan2' ? 'c' : wan === 'balanced' ? 'b' : 'd';
    tokens.push(d.mac + '|' + w);
  }

  var encoded = encodeURIComponent(tokens.join(','));
  fetch(window.location.pathname, {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'pairs=' + encoded
  })
    .then(function(r){ return r.json(); })
    .then(function(data){
      if (data.ok) {
        showToast(data.msg || 'Saved.', 'ok');
        refreshDevices();  // re-fetch to confirm persisted state; also clears dirty
      } else {
        showToast(data.msg || 'Save failed.', 'err');
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save & apply';
      }
    })
    .catch(function(e){
      showToast('Save failed: ' + e.message, 'err');
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save & apply';
    });
}

// ---- add device -------------------------------------------------------------
function addDevice() {
  var macInput = document.getElementById('add-mac');
  var wanSel = document.getElementById('add-wan');
  var mac = macInput.value.trim().toLowerCase();

  // basic client-side format check (server re-validates)
  if (!/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/.test(mac)) {
    showToast('Invalid MAC address format (need aa:bb:cc:dd:ee:ff)', 'err');
    return;
  }

  // check not already in table
  for (var i = 0; i < devices.length; i++) {
    if (devices[i].mac === mac) {
      showToast('Device ' + mac + ' is already in the table.', 'err');
      return;
    }
  }

  var wanCode = wanSel.value;
  var wan = wanCode === 'v' ? 'wan1' : wanCode === 'c' ? 'wan2' : wanCode === 'b' ? 'balanced' : 'default';

  // add to local state and mark as override
  devices.push({mac: mac, ip: '-', name: '', vendor: '', custom_name: '', online: false, wan: 'default', up_kbps: 0, down_kbps: 0});
  overrides[mac] = wan;

  macInput.value = '';
  renderTable();
  updateDirty();
  showToast('Added ' + mac + ' to table. Hit Save to apply.', 'ok');
}

// ---- filter -----------------------------------------------------------------
function filterRows() {
  var filter = document.getElementById('search').value.toLowerCase();
  var rows = document.querySelectorAll('#dev-body tr[data-mac]');
  for (var i = 0; i < rows.length; i++) {
    var tr = rows[i];
    var mac = tr.dataset.mac || '';
    var cells = tr.querySelectorAll('td');
    var ip   = cells[1] ? cells[1].textContent : '';
    var name = cells[3] ? cells[3].textContent : '';
    var haystack = (ip + ' ' + mac + ' ' + name).toLowerCase();
    tr.classList.toggle('hidden-row', filter !== '' && haystack.indexOf(filter) === -1);
  }
}

// ---- summary ----------------------------------------------------------------
function updateSummary(total, nDef, nW1, nW2, nBal) {
  var el = document.getElementById('count-summary');
  if (total === 0) { el.innerHTML = ''; return; }
  el.innerHTML = '';
  var t = document.createTextNode(total + ' device' + (total !== 1 ? 's' : '') + ' · ');
  el.appendChild(t);
  var bd = document.createElement('b'); bd.textContent = nDef + ' default';
  el.appendChild(bd);
  if (nW1 > 0) {
    el.appendChild(document.createTextNode(', '));
    var b1 = document.createElement('b'); b1.style.color='#4da3ff'; b1.textContent = nW1 + ' ' + WAN1_LABEL;
    el.appendChild(b1);
  }
  if (nW2 > 0) {
    el.appendChild(document.createTextNode(', '));
    var b2 = document.createElement('b'); b2.style.color='#d2a8ff'; b2.textContent = nW2 + ' ' + WAN2_LABEL;
    el.appendChild(b2);
  }
  if (nBal > 0) {
    el.appendChild(document.createTextNode(', '));
    var bb = document.createElement('b'); bb.style.color='#e3b341'; bb.textContent = nBal + ' Auto';
    el.appendChild(bb);
  }
}

// ---- toast ------------------------------------------------------------------
function showToast(msg, cls) {
  var el = document.getElementById('toast');
  if (!msg) { el.className = 'toast'; el.textContent = ''; return; }
  el.className = 'toast ' + cls;
  el.textContent = msg;
  if (cls === 'ok') {
    clearTimeout(el._timer);
    el._timer = setTimeout(function(){ el.className = 'toast'; el.textContent = ''; }, 4000);
  }
}
</script>
</body>
</html>
HTMLHEAD
