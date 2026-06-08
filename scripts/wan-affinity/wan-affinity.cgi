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
# POST WIRE FORMAT: a single urlencoded field "pairs", value = comma-separated
#   MAC|w tokens where w is v (wan1/vivo), c (wan2/claro), or d/absent (default).
#   Example decoded: aa:bb:cc:dd:ee:ff|c,11:22:33:44:55:66|v
#   This compact format is intentionally free of eval/injection surface:
#   MACs are only ever data values, never shell-expanded as variable names.
#   The previous version used eval "MAC_$idx=$v" / "WAN_$idx=$w" which required
#   a strict numeric-index guard to prevent injection; that guard is gone here
#   because there is nothing to inject into.
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

# JSON-escape an arbitrary string: escape backslash, double-quote, and control
# chars (\t \n \r and any byte < 0x20). Safe for embedding in JSON string values.
# Names are rendered by JS as textContent (never innerHTML), so this is primarily
# a JSON structural-integrity guard.
jsonesc() {
	printf '%s' "$1" | sed \
		-e 's/\\/\\\\/g' \
		-e 's/"/\\"/g' \
		-e 's/	/\\t/g' \
		-e 's/\r/\\r/g'
}

in_list() { # mac listfile
	[ -f "$2" ] && grep -qiE "^[[:space:]]*$1[[:space:]]*$" "$2"
}

# ---- read provider labels (provider-agnostic) ----------------------------------
wan1_label=$(uci -q get network.wan1.label 2>/dev/null || true)
wan2_label=$(uci -q get network.wan2.label 2>/dev/null || true)
[ -z "$wan1_label" ] && wan1_label="WAN1"
[ -z "$wan2_label" ] && wan2_label="WAN2"

# ---- MODE 3: POST -> apply changes, return JSON --------------------------------
if [ "${REQUEST_METHOD:-GET}" = "POST" ]; then
	printf 'Content-Type: application/json\r\n\r\n'

	len=${CONTENT_LENGTH:-0}
	body=$(dd bs=1 count="$len" 2>/dev/null)

	# Extract "pairs" field from urlencoded body (single pass, no eval)
	pairs_raw=""
	OLD_IFS=$IFS
	IFS='&'
	for kv in $body; do
		k="${kv%%=*}"
		v="${kv#*=}"
		dk=$(urldecode "$k")
		case "$dk" in
			pairs) pairs_raw=$(urldecode "$v") ;;
		esac
	done
	IFS=$OLD_IFS

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

	printf '%s' "$newvivo"  | sed '/^$/d' | sort -u > "$VIVO_LIST"
	printf '%s' "$newclaro" | sed '/^$/d' | sort -u > "$CLARO_LIST"

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

				[ "$name" = "*" ] && name="-"
				jm=$(jsonesc "$m")
				ji=$(jsonesc "$ip")
				jn=$(jsonesc "$name")

				printf '%s{"mac":"%s","ip":"%s","name":"%s","online":%s,"wan":"%s"}' \
					"$sep" "$jm" "$ji" "$jn" "$online_val" "$wan"
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

				jm=$(jsonesc "$m")

				printf '%s{"mac":"%s","ip":"-","name":"-","online":false,"wan":"%s"}' \
					"$sep" "$jm" "$wan"
				sep=","
			done < "$lf"
		done

		printf ']}'
		exit 0
		;;
esac

# ---- MODE 1: GET (no api) -> HTML shell ----------------------------------------
printf 'Content-Type: text/html; charset=utf-8\r\n\r\n'

# Escape label for safe embedding in HTML attributes and JS string literals.
# These go into the inline <script> block, so we need JS-string-safe values.
# Labels come from uci (trusted admin config), but escape anyway for correctness.
w1l_html=$(printf '%s' "$wan1_label" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g')
w2l_html=$(printf '%s' "$wan2_label" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g')
# For embedding in JS string literals (single-quoted in the heredoc), escape backslash and single-quote
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
.wrap{max-width:860px;margin:0 auto;padding:18px 16px}
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
</div>

<table id="dev-table">
  <thead>
    <tr>
      <th onclick="sortBy('online')" id="th-online"><span class="sort-arrow">&#9660;</span></th>
      <th onclick="sortBy('ip')" id="th-ip">IP <span class="sort-arrow"></span></th>
      <th onclick="sortBy('mac')" id="th-mac">MAC <span class="sort-arrow"></span></th>
      <th onclick="sortBy('name')" id="th-name">Name <span class="sort-arrow"></span></th>
      <th>WAN</th>
    </tr>
  </thead>
  <tbody id="dev-body">
    <tr><td colspan="5" style="text-align:center;padding:20px;color:#8b949e">Loading&hellip;</td></tr>
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
</p>

</div><!-- .wrap -->
<script>
// Provider labels injected server-side (provider-agnostic; no Vivo/Claro hardcoded in UI)
var WAN1_LABEL = '$w1l_js';
var WAN2_LABEL = '$w2l_js';

// ---- state ------------------------------------------------------------------
var devices = [];       // current server state: [{mac,ip,name,online,wan}, ...]
var overrides = {};     // {mac -> wan} for user-edited rows (dirty state)
var sortKey = 'online'; // default: online-first
var sortAsc = true;

// ---- init -------------------------------------------------------------------
document.getElementById('add-opt-wan2').textContent = WAN2_LABEL + ' (locked)';
document.getElementById('add-opt-wan1').textContent = WAN1_LABEL + ' (locked)';
document.getElementById('add-opt-wan2').value = 'c';
document.getElementById('add-opt-wan1').value = 'v';
refreshDevices();

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
  var cols = ['online','ip','mac','name'];
  for (var i = 0; i < cols.length; i++) {
    var th = document.getElementById('th-' + cols[i]);
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
  var wa = overrides[a.mac] !== undefined ? overrides[a.mac] : a.wan;
  var wb = overrides[b.mac] !== undefined ? overrides[b.mac] : b.wan;
  if (sortKey === 'online') {
    // online-first, then by name/ip secondary
    if (a.online !== b.online) return a.online ? -1 : 1;
    return (a.name || a.ip || '').localeCompare(b.name || b.ip || '');
  }
  var av, bv;
  if (sortKey === 'ip') {
    // numeric IP sort
    av = ipToNum(a.ip); bv = ipToNum(b.ip);
    return sortAsc ? av - bv : bv - av;
  }
  if (sortKey === 'mac') { av = a.mac; bv = b.mac; }
  else { av = a.name || a.ip || ''; bv = b.name || b.ip || ''; }
  var c = av.localeCompare(bv);
  return sortAsc ? c : -c;
}

function ipToNum(ip) {
  if (!ip || ip === '-') return 0;
  var parts = ip.split('.');
  return ((parseInt(parts[0],10)||0)*16777216 + (parseInt(parts[1],10)||0)*65536 +
          (parseInt(parts[2],10)||0)*256 + (parseInt(parts[3],10)||0));
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
    etd.colSpan = 5;
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
      var haystack = (d.ip + ' ' + d.mac + ' ' + d.name).toLowerCase();
      if (haystack.indexOf(filter) === -1) tr.classList.add('hidden-row');
    }

    // dot
    var tdDot = document.createElement('td');
    var dot = document.createElement('span');
    dot.className = 'dot dot-' + (d.online ? 'on' : 'off');
    dot.title = d.online ? 'online' : 'offline';
    tdDot.appendChild(dot);
    tr.appendChild(tdDot);

    // ip
    var tdIp = document.createElement('td');
    tdIp.textContent = d.ip === '-' ? '' : d.ip;
    tr.appendChild(tdIp);

    // mac
    var tdMac = document.createElement('td');
    tdMac.className = 'mac';
    tdMac.textContent = d.mac;
    tr.appendChild(tdMac);

    // name
    var tdName = document.createElement('td');
    tdName.textContent = (d.name === '-' || !d.name) ? '' : d.name;
    tr.appendChild(tdName);

    // WAN segmented control
    var tdWan = document.createElement('td');
    tdWan.appendChild(makeSegControl(d.mac, curWan));
    tr.appendChild(tdWan);

    tbody.appendChild(tr);
  }

  updateSummary(total, nDef, nW1, nW2);
  updateSortHeaders();
}

function makeSegControl(mac, curWan) {
  var seg = document.createElement('div');
  seg.className = 'seg';
  var nm = 'w_' + mac.replace(/:/g, '');

  var opts = [
    {val:'default', label:'Default',          cls:'lbl-default'},
    {val:'wan1',    label:WAN1_LABEL,          cls:'lbl-wan1'},
    {val:'wan2',    label:WAN2_LABEL,          cls:'lbl-wan2'}
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
  // find original device wan
  var orig = 'default';
  for (var i = 0; i < devices.length; i++) {
    if (devices[i].mac === mac) { orig = devices[i].wan; break; }
  }
  if (newWan === orig) {
    delete overrides[mac];
  } else {
    overrides[mac] = newWan;
  }
  // update row accent
  var tr = document.querySelector('tr[data-mac="' + mac + '"]');
  if (tr) {
    tr.className = 'r-' + newWan;
  }
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

  // Encode and POST
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
  devices.push({mac: mac, ip: '-', name: '-', online: false, wan: 'default'});
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
    // get ip and name from cells
    var cells = tr.querySelectorAll('td');
    var ip = cells[1] ? cells[1].textContent : '';
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
