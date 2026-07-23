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
#     MAC|w tokens where w is v (wan1/vivo), c (wan2/claro), or d/absent (default).
#     Example decoded: aa:bb:cc:dd:ee:ff|c,11:22:33:44:55:66|v
#   action=rename: fields "mac" and "name". Updates names.list.
#     Returns {"ok":true,"msg":"Name saved."} or {"ok":false,"msg":"..."}.
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

	# ---- action=save (default): bulk WAN assignment ----------------------------
	newvivo=""
	newclaro=""

	# Parse: split on comma, then split each token on pipe
	OLD_IFS=$IFS
	IFS=','
	for token in $pairs_raw; do
		mac_part="${token%%|*}"
		wan_part="${token#*|}"
		[ "$wan_part" = "$token" ] && wan_part="d"  # no pipe -> default
		cm=$(norm_mac "$mac_part")
		[ -z "$cm" ] && continue  # discard invalid MACs silently
		case "$wan_part" in
			v) newvivo="$newvivo$cm
" ;;
			c) newclaro="$newclaro$cm
" ;;
			*) ;;  # d or anything else -> default (not in either list)
		esac
	done
	IFS=$OLD_IFS

	# Atomic list writes: temp in $WA_DIR so mv is a same-filesystem rename (not a
	# cross-fs copy), matching the names.list pattern at lines 164-169 above.
	_tmp_vivo=$(mktemp "$WA_DIR/.vivo.XXXXXX")
	printf '%s' "$newvivo"  | sed '/^$/d' | sort -u > "$_tmp_vivo"
	mv "$_tmp_vivo" "$VIVO_LIST"
	_tmp_claro=$(mktemp "$WA_DIR/.claro.XXXXXX")
	printf '%s' "$newclaro" | sed '/^$/d' | sort -u > "$_tmp_claro"
	mv "$_tmp_claro" "$CLARO_LIST"

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

		printf '{"meta":{"wan1_label":"%s","wan2_label":"%s","table100_dev":"%s","table101_dev":"%s"},"devices":[' \
			"$w1l" "$w2l" "$t100e" "$t101e"

		sep=""
		seen=" "

		# devices from dhcp leases
		if [ -f "$LEASES" ]; then
			while read -r _exp mac ip name _cid; do
				[ -z "$mac" ] && continue
				m=$(printf '%s' "$mac" | tr 'A-F' 'a-f')
				case "$seen" in *" $m "*) continue ;; esac
				seen="$seen$m "

				wan="default"
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

		# locked-but-offline devices not in current leases
		for lf in "$VIVO_LIST" "$CLARO_LIST"; do
			[ -f "$lf" ] || continue
			while IFS= read -r line; do
				m=$(echo "$line" | sed 's/#.*//; s/[[:space:]]//g' | tr 'A-F' 'a-f')
				[ -z "$m" ] && continue
				case "$seen" in *" $m "*) continue ;; esac
				seen="$seen$m "

				wan="default"
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
body{margin:0;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0e1116;color:#e6edf3}
.wrap{max-width:960px;margin:0 auto;padding:18px 16px}
/* ---- header bar ---- */
.hdr{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 4px}
h1{font-size:19px;margin:0;flex:1 1 auto}
.hdr-right{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.count-summary{color:#8b949e;font-size:13px}
.count-summary b{color:#e6edf3}
/* ---- toolbar ---- */
.toolbar{display:flex;gap:8px;align-items:center;margin:12px 0;flex-wrap:wrap}
.toolbar input[type=search]{background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:7px 10px;font-size:13px;width:220px;flex:1 1 160px;max-width:320px}
.toolbar input[type=search]::placeholder{color:#484f58}
.live-label{font-size:13px;color:#8b949e;display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none}
.live-label input{cursor:pointer}
/* ---- meta line ---- */
.meta{color:#8b949e;font-size:13px;margin:0 0 12px}
.meta b{color:#e6edf3}
/* ---- toast ---- */
.toast{padding:10px 14px;border-radius:8px;margin:0 0 14px;font-size:14px;display:none}
.toast.ok{background:#10301a;border:1px solid #1f6f37;color:#5ff08a;display:block}
.toast.err{background:#3a1414;border:1px solid #8b2a2a;color:#ff9b9b;display:block}
/* ---- table ---- */
table{width:100%;border-collapse:collapse;background:#161b22;border-radius:10px;overflow:hidden}
th,td{padding:9px 10px;text-align:left;border-bottom:1px solid #21262d;font-size:14px;vertical-align:middle}
th{background:#1c2230;color:#9da7b3;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.4px;cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:#e6edf3}
th .sort-arrow{font-size:10px;opacity:.5;margin-left:3px}
th.active-sort .sort-arrow{opacity:1;color:#58a6ff}
tr:last-child td{border-bottom:none}
tr.hidden-row{display:none}
.mac{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;color:#c9d1d9}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;flex-shrink:0}
.dot-on{background:#3fb950;box-shadow:0 0 0 2px #10301a}
.dot-off{background:#484f58}
/* row accent by WAN assignment */
.r-wan1 td:first-child{border-left:3px solid #58a6ff}
.r-wan2 td:first-child{border-left:3px solid #d2a8ff}
.r-default td:first-child{border-left:3px solid transparent}
/* ---- segmented WAN control ---- */
.seg{display:inline-flex;border:1px solid #30363d;border-radius:6px;overflow:hidden;font-size:12px}
.seg label{padding:5px 9px;cursor:pointer;color:#8b949e;white-space:nowrap;transition:background .12s,color .12s}
.seg input[type=radio]{display:none}
.seg input:checked + label.lbl-default{background:#1f3a1f;color:#5ff08a}
.seg input:checked + label.lbl-wan1{background:#132a45;color:#58a6ff}
.seg input:checked + label.lbl-wan2{background:#2c1f45;color:#d2a8ff}
.seg label:hover{background:#21262d;color:#e6edf3}
/* ---- buttons ---- */
button{border:0;border-radius:8px;padding:8px 16px;font-size:14px;font-weight:600;cursor:pointer;transition:background .12s}
.btn-save{background:#238636;color:#fff}
.btn-save:hover{background:#2ea043}
.btn-save:disabled{background:#161b22;color:#484f58;cursor:not-allowed;border:1px solid #30363d}
.btn-refresh{background:#21262d;color:#c9d1d9;border:1px solid #30363d}
.btn-refresh:hover{background:#2d333b}
.btn-refresh:disabled{opacity:.5;cursor:not-allowed}
/* ---- spinner ---- */
.spin{display:inline-block;width:14px;height:14px;border:2px solid #484f58;border-top-color:#58a6ff;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:4px}
@keyframes spin{to{transform:rotate(360deg)}}
/* ---- dirty badge ---- */
.dirty-badge{font-size:12px;color:#e3b341;background:#2d2207;border:1px solid #6a4a0a;border-radius:6px;padding:3px 8px;display:none}
.dirty-badge.show{display:inline-block}
/* ---- name cell ---- */
.name-wrap{display:flex;align-items:center;gap:5px;min-width:0}
.name-edit-btn{background:none;border:none;padding:1px 4px;font-size:13px;color:#484f58;cursor:pointer;border-radius:4px;line-height:1;flex-shrink:0}
.name-edit-btn:hover{color:#8b949e;background:#21262d}
.name-vendor{color:#8b949e;font-style:italic;font-size:13px}
.name-input{background:#0d1117;color:#e6edf3;border:1px solid #58a6ff;border-radius:5px;padding:3px 6px;font-size:13px;min-width:80px;width:160px}
/* ---- rate columns ---- */
td.rate{font-variant-numeric:tabular-nums;font-size:13px;color:#8b949e;text-align:right;white-space:nowrap}
td.rate.active{color:#e6edf3}
.rate-muted{color:#484f58}
/* ---- add-device panel ---- */
.add-panel{margin-top:18px;padding:14px;background:#161b22;border:1px solid #21262d;border-radius:10px}
.add-panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.4px;color:#9da7b3;margin:0 0 10px}
.add-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.add-panel input[type=text]{background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:7px 9px;font-family:ui-monospace,monospace;font-size:13px;width:210px}
.add-panel select{background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px 8px;font-size:13px}
.btn-add{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:7px 14px;font-size:13px}
.btn-add:hover{background:#2d333b}
/* ---- empty state ---- */
.empty-row td{color:#8b949e;text-align:center;padding:28px 10px;font-style:italic}
/* ---- legend ---- */
.legend{color:#8b949e;font-size:12px;margin-top:10px}
@media(max-width:600px){
  .seg label{padding:5px 6px;font-size:11px}
  td,th{padding:7px 6px;font-size:13px}
  .mac{font-size:11px}
  .col-down,.col-up{display:none}
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
      <th onclick="sortBy('online')" id="th-online"><span class="sort-arrow">&#9660;</span></th>
      <th onclick="sortBy('ip')" id="th-ip">IP <span class="sort-arrow"></span></th>
      <th onclick="sortBy('mac')" id="th-mac">MAC <span class="sort-arrow"></span></th>
      <th onclick="sortBy('name')" id="th-name">Name <span class="sort-arrow"></span></th>
      <th onclick="sortBy('down_kbps')" id="th-down" class="col-down">&#8595; Down <span class="sort-arrow"></span></th>
      <th onclick="sortBy('up_kbps')" id="th-up" class="col-up">&#8593; Up <span class="sort-arrow"></span></th>
      <th>WAN</th>
    </tr>
  </thead>
  <tbody id="dev-body">
    <tr><td colspan="7" style="text-align:center;padding:20px;color:#8b949e">Loading&hellip;</td></tr>
  </tbody>
</table>

<div class="add-panel">
  <h2>Add a device by MAC</h2>
  <div class="add-row">
    <input type="text" id="add-mac" placeholder="aa:bb:cc:dd:ee:ff" autocomplete="off" autocapitalize="off" spellcheck="false">
    <select id="add-wan">
      <option value="c" id="add-opt-wan2"></option>
      <option value="v" id="add-opt-wan1"></option>
      <option value="d">Default</option>
    </select>
    <button class="btn-add" onclick="addDevice()">Add</button>
  </div>
  <p class="legend">For a device that has not yet requested DHCP. It will appear in the table and be included in the next Save.</p>
</div>

<p class="legend">
  Green dot = currently reachable (REACHABLE/STALE/DELAY/PROBE in ARP table).
  &ldquo;Default&rdquo; = unlocked device follows the default WAN.
  Locking pins the device to one WAN with automatic failover.
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
    updateSummary(0, 0, 0, 0);
    return;
  }

  var filter = document.getElementById('search').value.toLowerCase();
  var total = sorted.length, nDef = 0, nW1 = 0, nW2 = 0;

  for (var i = 0; i < sorted.length; i++) {
    var d = sorted[i];
    var curWan = overrides[d.mac] !== undefined ? overrides[d.mac] : d.wan;
    if (curWan === 'wan1') nW1++;
    else if (curWan === 'wan2') nW2++;
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
    var dot = document.createElement('span');
    dot.className = 'dot dot-' + (d.online ? 'on' : 'off');
    dot.title = d.online ? 'online' : 'offline';
    tdDot.appendChild(dot);
    tr.appendChild(tdDot);

    // col: ip
    var tdIp = document.createElement('td');
    tdIp.textContent = d.ip === '-' ? '' : d.ip;
    tr.appendChild(tdIp);

    // col: mac
    var tdMac = document.createElement('td');
    tdMac.className = 'mac';
    tdMac.textContent = d.mac;
    tr.appendChild(tdMac);

    // col: name (with inline edit)
    var tdName = document.createElement('td');
    tdName.appendChild(makeNameCell(d));
    tr.appendChild(tdName);

    // col: down rate
    var tdDown = document.createElement('td');
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
    tr.appendChild(tdWan);

    tbody.appendChild(tr);
  }

  updateSummary(total, nDef, nW1, nW2);
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
    {val:'default', label:'Default',   cls:'lbl-default'},
    {val:'wan1',    label:WAN1_LABEL,  cls:'lbl-wan1'},
    {val:'wan2',    label:WAN2_LABEL,  cls:'lbl-wan2'}
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
    var w = wan === 'wan1' ? 'v' : wan === 'wan2' ? 'c' : 'd';
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
  var wan = wanCode === 'v' ? 'wan1' : wanCode === 'c' ? 'wan2' : 'default';

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
function updateSummary(total, nDef, nW1, nW2) {
  var el = document.getElementById('count-summary');
  if (total === 0) { el.innerHTML = ''; return; }
  el.innerHTML = '';
  var t = document.createTextNode(total + ' device' + (total !== 1 ? 's' : '') + ' · ');
  el.appendChild(t);
  var bd = document.createElement('b'); bd.textContent = nDef + ' default';
  el.appendChild(bd);
  if (nW1 > 0) {
    el.appendChild(document.createTextNode(', '));
    var b1 = document.createElement('b'); b1.style.color='#58a6ff'; b1.textContent = nW1 + ' ' + WAN1_LABEL;
    el.appendChild(b1);
  }
  if (nW2 > 0) {
    el.appendChild(document.createTextNode(', '));
    var b2 = document.createElement('b'); b2.style.color='#d2a8ff'; b2.textContent = nW2 + ' ' + WAN2_LABEL;
    el.appendChild(b2);
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
