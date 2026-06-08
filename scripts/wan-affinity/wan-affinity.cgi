#!/bin/sh
# /www/cgi-bin/wan-affinity  (uhttpd CGI)
#
# Device-management web UI for per-device WAN affinity.
#   GET  -> list connected devices (online dot, IP, MAC, name, current WAN) with
#           a per-device WAN selector, plus a manual "add MAC" row.
#   POST -> rewrite /etc/wan-affinity/{claro,vivo}.list from the form and run
#           apply-affinity.sh, so routing changes are live the moment you Save.
#
# Device discovery: /tmp/dhcp.leases (IP/MAC/name) merged with any locked MACs
# that are currently offline (so a device's lock is never silently dropped).
# Current WAN per device is read straight from the lock lists - the same source
# of truth apply-affinity.sh uses - so the page always shows the effective state.
#
# Unauthenticated by design: this is the trusted LAN / Tailscale admin surface,
# same posture as LuCI on this box (uhttpd input is firewalled off the WANs).

WA_DIR=/etc/wan-affinity
CLARO_LIST="$WA_DIR/claro.list"
VIVO_LIST="$WA_DIR/vivo.list"
APPLY=/usr/lib/wan-affinity/apply-affinity.sh
LEASES=/tmp/dhcp.leases

mkdir -p "$WA_DIR"

# %XX + '+' -> bytes
urldecode() {
	s=$(printf '%s' "$1" | sed 's/+/ /g; s/%/\\x/g')
	printf '%b' "$s"
}

# lowercase + validate; echoes the mac on success, empty on failure
norm_mac() {
	m=$(printf '%s' "$1" | tr 'A-F' 'a-f' | sed 's/[[:space:]]//g')
	echo "$m" | grep -qE '^([0-9a-f]{2}:){5}[0-9a-f]{2}$' && printf '%s' "$m"
}

# minimal HTML escape for untrusted lease hostnames
htmlesc() {
	printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g'
}

in_list() { # mac listfile
	[ -f "$2" ] && grep -qiE "^[[:space:]]*$1[[:space:]]*$" "$2"
}

MSG=""
MSG_CLASS="ok"

# ---- POST: rewrite lists + apply --------------------------------------------
if [ "${REQUEST_METHOD:-GET}" = "POST" ]; then
	len=${CONTENT_LENGTH:-0}
	body=$(dd bs=1 count="$len" 2>/dev/null)

	OLD_IFS=$IFS
	IFS='&'
	for kv in $body; do
		k=${kv%%=*}
		v=${kv#*=}
		k=$(urldecode "$k")
		v=$(urldecode "$v")
		# Only accept numeric indices - the index becomes a shell variable
		# name via eval, so a non-numeric key would be an injection vector.
		case "$k" in
			mac_*) idx=${k#mac_}; case "$idx" in ''|*[!0-9]*) ;; *) eval "MAC_$idx=\$v" ;; esac ;;
			wan_*) idx=${k#wan_}; case "$idx" in ''|*[!0-9]*) ;; *) eval "WAN_$idx=\$v" ;; esac ;;
			addmac) ADDMAC=$v ;;
			addwan) ADDWAN=$v ;;
		esac
	done
	IFS=$OLD_IFS

	newclaro=""
	newvivo=""
	i=0
	while [ $i -lt 512 ]; do
		eval "mm=\${MAC_$i:-}"
		eval "ww=\${WAN_$i:-}"
		if [ -n "$mm" ]; then
			cm=$(norm_mac "$mm")
			if [ -n "$cm" ]; then
				case "$ww" in
					claro) newclaro="$newclaro$cm
" ;;
					vivo)  newvivo="$newvivo$cm
" ;;
				esac
			fi
		fi
		i=$((i + 1))
	done

	if [ -n "${ADDMAC:-}" ]; then
		cm=$(norm_mac "$ADDMAC")
		if [ -n "$cm" ]; then
			case "${ADDWAN:-}" in
				claro) newclaro="$newclaro$cm
" ;;
				vivo)  newvivo="$newvivo$cm
" ;;
			esac
		elif [ -n "$(printf '%s' "$ADDMAC" | tr -d '[:space:]')" ]; then
			MSG="Ignored invalid MAC '$(htmlesc "$ADDMAC")' (need aa:bb:cc:dd:ee:ff)."
			MSG_CLASS="err"
		fi
	fi

	printf '%s' "$newclaro" | sed '/^$/d' | sort -u > "$CLARO_LIST"
	printf '%s' "$newvivo"  | sed '/^$/d' | sort -u > "$VIVO_LIST"

	if [ -x "$APPLY" ]; then
		if out=$("$APPLY" 2>&1); then
			[ "$MSG_CLASS" = "err" ] || MSG="Saved and applied. Routing is live now."
		else
			MSG="apply error: $(htmlesc "$out")"
			MSG_CLASS="err"
		fi
	else
		MSG="ERROR: $APPLY missing - run configure-wan-affinity.sh."
		MSG_CLASS="err"
	fi
fi

# ---- shared render helpers --------------------------------------------------
NEIGH=$(ip neigh show 2>/dev/null)
online() { echo "$NEIGH" | grep -qE "^$1 .*(REACHABLE|STALE|DELAY|PROBE)"; }

render_row() { # idx mac ip name
	ri=$1; rm=$2; rip=$3; rname=$4
	cur=default
	in_list "$rm" "$VIVO_LIST"  && cur=vivo
	in_list "$rm" "$CLARO_LIST" && cur=claro
	st=off
	[ "$rip" != "-" ] && online "$rip" && st=on
	[ "$rname" = "*" ] && rname="-"
	rname=$(htmlesc "$rname")
	sd=""; sv=""; sc=""
	case "$cur" in
		default) sd=" selected" ;;
		vivo)    sv=" selected" ;;
		claro)   sc=" selected" ;;
	esac
	cat <<ROW
<tr class="r-$cur">
<td><span class="dot dot-$st" title="$st"></span></td>
<td>$rip</td>
<td class="mac">$rm</td>
<td>$rname</td>
<td>
<input type="hidden" name="mac_$ri" value="$rm">
<select name="wan_$ri">
<option value="default"$sd>Vivo - default</option>
<option value="vivo"$sv>Vivo - locked</option>
<option value="claro"$sc>Claro - locked</option>
</select>
</td></tr>
ROW
}

# ---- output -----------------------------------------------------------------
printf 'Content-Type: text/html; charset=utf-8\r\n\r\n'

v100=$(ip route show table 100 2>/dev/null | awk '/^default/{print $5; exit}')
v101=$(ip route show table 101 2>/dev/null | awk '/^default/{print $5; exit}')
[ -n "$v100" ] || v100="(down)"
[ -n "$v101" ] || v101="(down)"

cat <<'HEAD'
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
.wrap{max-width:820px;margin:0 auto;padding:18px}
h1{font-size:19px;margin:0 0 4px}
.sub{color:#8b949e;font-size:13px;margin:0 0 14px}
.meta{color:#8b949e;font-size:13px;margin:0 0 14px}
.meta b{color:#e6edf3}
.msg{padding:10px 12px;border-radius:8px;margin:0 0 14px;font-size:14px}
.msg.ok{background:#10301a;border:1px solid #1f6f37;color:#5ff08a}
.msg.err{background:#3a1414;border:1px solid #8b2a2a;color:#ff9b9b}
table{width:100%;border-collapse:collapse;background:#161b22;border-radius:10px;overflow:hidden}
th,td{padding:9px 10px;text-align:left;border-bottom:1px solid #21262d;font-size:14px}
th{background:#1c2230;color:#9da7b3;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
tr:last-child td{border-bottom:none}
.mac{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;color:#c9d1d9}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%}
.dot-on{background:#3fb950;box-shadow:0 0 0 2px #10301a}
.dot-off{background:#484f58}
select{background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:5px 7px;font-size:13px}
.r-claro td:nth-child(3){color:#d2a8ff}
.r-vivo td:nth-child(3){color:#79c0ff}
.bar{display:flex;gap:10px;align-items:center;margin:16px 0;flex-wrap:wrap}
button{background:#238636;color:#fff;border:0;border-radius:8px;padding:10px 18px;font-size:15px;font-weight:600;cursor:pointer}
button:hover{background:#2ea043}
.add{margin-top:18px;padding:14px;background:#161b22;border:1px solid #21262d;border-radius:10px}
.add h2{font-size:13px;text-transform:uppercase;letter-spacing:.4px;color:#9da7b3;margin:0 0 10px}
.add input[type=text]{background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:7px 9px;font-family:ui-monospace,monospace;font-size:13px;width:200px}
.legend{color:#8b949e;font-size:12px;margin-top:10px}
</style>
</head>
<body>
<div class="wrap">
<h1>WAN Affinity - device routing</h1>
<p class="sub">Pick a WAN per device. Hit Save and the rule applies immediately. Each device keeps one stable public IP.</p>
HEAD

echo "<p class=\"meta\">Vivo (table 100) via <b>$v100</b> &middot; Claro (table 101) via <b>$v101</b></p>"
[ -n "$MSG" ] && echo "<div class=\"msg $MSG_CLASS\">$MSG</div>"

cat <<'FORMTOP'
<form method="post">
<table>
<thead><tr><th></th><th>IP</th><th>MAC</th><th>Name</th><th>WAN</th></tr></thead>
<tbody>
FORMTOP

idx=0
seen=" "
if [ -f "$LEASES" ]; then
	while read -r _exp mac ip name _cid; do
		[ -z "$mac" ] && continue
		m=$(printf '%s' "$mac" | tr 'A-F' 'a-f')
		seen="$seen$m "
		render_row "$idx" "$m" "$ip" "$name"
		idx=$((idx + 1))
	done < "$LEASES"
fi

# locked-but-offline devices (not in current leases)
for lf in "$VIVO_LIST" "$CLARO_LIST"; do
	[ -f "$lf" ] || continue
	while IFS= read -r line; do
		m=$(echo "$line" | sed 's/#.*//; s/[[:space:]]//g' | tr 'A-F' 'a-f')
		[ -z "$m" ] && continue
		case "$seen" in *" $m "*) continue ;; esac
		seen="$seen$m "
		render_row "$idx" "$m" "-" "(offline)"
		idx=$((idx + 1))
	done < "$lf"
done

cat <<'FORMBOT'
</tbody>
</table>
<div class="bar"><button type="submit">Save &amp; apply</button></div>
<div class="add">
<h2>Add a device by MAC</h2>
<input type="text" name="addmac" placeholder="aa:bb:cc:dd:ee:ff" autocomplete="off" autocapitalize="off" spellcheck="false">
<select name="addwan">
<option value="claro">Claro - locked</option>
<option value="vivo">Vivo - locked</option>
</select>
<span class="legend">For a device that has not requested DHCP yet.</span>
</div>
<p class="legend">Green dot = currently reachable. "Vivo - default" = unlocked (follows the default WAN). Locking pins the device to one WAN with automatic failover.</p>
</form>
</div>
</body>
</html>
FORMBOT
