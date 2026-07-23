#!/bin/sh
# /www/cgi-bin/nexus  (uhttpd CGI)
#
# Unified NexusGate web UI. Three tabs:
#   Devices   - embeds /cgi-bin/wan-affinity (iframe). ALL mutations stay in
#               wan-affinity.cgi -> apply-affinity.sh; this script is READ-ONLY.
#   WAN Stats - per-WAN status, gateway, byte counters, live rates, and a
#               filtered logread tail (wan-affinity / omr-tracker / pppoe).
#   Topology  - internet -> WAN1/WAN2 -> router -> LAN devices, SVG-rendered,
#               device->WAN edges colored by affinity lock.
#
# MODES:
#   GET (no api)       -> HTML shell (tabs; JS fetches data)
#   GET ?api=stats     -> JSON {wans:[...], logs:[...]}
#   GET ?api=topology  -> JSON {wans:[...], devices:[...]}
#
# Same trust posture as wan-affinity.cgi: trusted LAN/Tailscale surface,
# uhttpd firewalled off the WANs. Read-only: no POST handler at all.

WA_DIR=/etc/wan-affinity
CLARO_LIST="$WA_DIR/claro.list"
VIVO_LIST="$WA_DIR/vivo.list"
NAMES_LIST="$WA_DIR/names.list"
OUI_DB=/usr/lib/wan-affinity/oui.db
LEASES=/tmp/dhcp.leases
# space-separated LAN-side interfaces for neighbor-table scoping (override via env)
LAN_IFS="${LAN_IFS:-br-lan}"

jsonesc() {
	printf '%s' "$1" | awk 'BEGIN{ORS=""} {gsub(/\\/,"\\\\");gsub(/"/,"\\\"");gsub(/\t/,"\\t");gsub(/\r/,"\\r"); if(NR>1) printf "\\n"; printf "%s",$0}'
}

in_list() { [ -f "$2" ] && grep -qiE "^[[:space:]]*$1[[:space:]]*$" "$2"; }

# lowercase + validate; echoes the mac on success, empty on failure
# (same validator as wan-affinity.cgi so the two surfaces agree)
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

cname() {
	[ -f "$NAMES_LIST" ] || return 0
	awk -F'|' -v m="$1" '$1==m{sub(/^[^|]*\|/,""); print; exit}' "$NAMES_LIST"
}

oui_vendor() {
	[ -f "$OUI_DB" ] || return 0
	p=$(printf '%s' "$1" | tr -d ':' | cut -c1-6 | tr 'a-f' 'A-F')
	awk -F'\t' -v k="$p" '$1==k{print $2; exit}' "$OUI_DB"
}

wan1_label=$(uci -q get network.wan1.label 2>/dev/null || true)
wan2_label=$(uci -q get network.wan2.label 2>/dev/null || true)
[ -z "$wan1_label" ] && wan1_label="WAN1"
[ -z "$wan2_label" ] && wan2_label="WAN2"

# table number -> "gw dev" (same source of truth as 098-wan-affinity)
_wan_route() { ip route show table "$1" 2>/dev/null | awk '/^default/{print $3" "$5;exit}'; }

# dev -> "rx_bytes tx_bytes" from /proc/net/dev
_counters() {
	awk -v d="$1:" '$1==d{print $2" "$10; exit}' /proc/net/dev 2>/dev/null
}

# One WAN's JSON object. args: key label table
_wan_json() {
	_k=$1; _l=$2; _t=$3
	set -- $(_wan_route "$_t"); _gw=${1:-}; _dev=${2:-}
	_up=0
	if [ -n "$_dev" ]; then
		ping -W1 -c1 -I "$_dev" 1.1.1.1 >/dev/null 2>&1 && _up=1 || {
			ping -W1 -c1 -I "$_dev" 8.8.8.8 >/dev/null 2>&1 && _up=1; }
	fi
	set -- $(_counters "$_dev"); _rx=${1:-0}; _tx=${2:-0}
	printf '{"key":"%s","label":"%s","dev":"%s","gw":"%s","up":%s,"rx_bytes":%s,"tx_bytes":%s}' \
		"$_k" "$(jsonesc "$_l")" "$(jsonesc "$_dev")" "$(jsonesc "$_gw")" "$_up" "$_rx" "$_tx"
}

case "${QUERY_STRING:-}" in

# ---- API: WAN stats + logs ---------------------------------------------------
*api=stats*)
	printf 'Content-Type: application/json\r\n\r\n'
	printf '{"ts":%s,"wans":[' "$(date +%s)"
	_wan_json wan1 "$wan1_label" 6
	printf ','
	_wan_json wan2 "$wan2_label" 10
	printf '],"logs":['
	_first=1
	logread 2>/dev/null | grep -iE 'wan-affinity|omr-tracker|pppoe|wan1|wan2|mptcp' | tail -n 200 | \
	while IFS= read -r line; do
		if [ "$_first" = 1 ]; then _first=0; else printf ','; fi
		printf '"%s"' "$(jsonesc "$line")"
	done
	printf ']}'
	;;

# ---- API: topology -----------------------------------------------------------
*api=topology*)
	printf 'Content-Type: application/json\r\n\r\n'
	printf '{"ts":%s,"wans":[' "$(date +%s)"
	_wan_json wan1 "$wan1_label" 6
	printf ','
	_wan_json wan2 "$wan2_label" 10
	printf '],"router":{"name":"NexusGate","lan":"br-lan"},"devices":['
	# LAN devices: dhcp leases + locked lists + neighbor table (neighbor-only
	# clients — e.g. static IPs, IPv6-only — must appear too). ip neigh is
	# snapshotted ONCE per response, not forked per device.
	# Neighbor snapshot, LAN-scoped: WAN gateway/ISP neighbors (pppoe-wan,
	# eth0.6, eth0.10, ...) must never surface as downstream devices.
	NEIGH=$(ip neigh show 2>/dev/null | awk -v ifs="$LAN_IFS" '
		BEGIN{n=split(ifs,a," ");for(i=1;i<=n;i++)ok[a[i]]=1}
		{for(i=1;i<NF;i++)if($i=="dev"&&ok[$(i+1)]){print;next}}')
	{
		[ -f "$LEASES" ] && awk '{print tolower($2)"|"$3"|"$4}' "$LEASES"
		for f in "$CLARO_LIST" "$VIVO_LIST"; do
			[ -f "$f" ] && sed 's/#.*//; s/[[:space:]]//g' "$f" | grep -v '^$' | \
				tr 'A-F' 'a-f' | sed 's/$/||/'
		done
		# neighbor-derived rows: "<ip> dev <if> lladdr <mac> <STATE>"
		printf '%s\n' "$NEIGH" | awk 'tolower($0) ~ /lladdr/ {
			for (i=1;i<NF;i++) if ($i=="lladdr") print tolower($(i+1))"|"$1"|"}'
	} | awk -F'|' '!seen[$1]++' | {
		_first=1
		while IFS='|' read -r mac ip lname; do
			mac=$(norm_mac "$mac")
			[ -z "$mac" ] && continue  # skip malformed lease/list rows
			n=$(cname "$mac")
			[ -z "$n" ] && [ "$lname" != "*" ] && n=$lname
			[ -z "$n" ] && n=$(oui_vendor "$mac")
			w=d
			in_list "$mac" "$CLARO_LIST" && w=c
			in_list "$mac" "$VIVO_LIST" && w=v
			# reachability + full address set from the cached neighbor snapshot
			nlines=$(printf '%s\n' "$NEIGH" | grep -i "lladdr $mac")
			on=0
			printf '%s\n' "$nlines" | grep -qE 'REACHABLE|STALE|DELAY|PROBE' && on=1
			ips=$( { [ -n "$ip" ] && printf '%s\n' "$ip"
				printf '%s\n' "$nlines" | awk 'NF{print $1}'
				} | awk '!seen[$0]++' )
			ipjson=$(printf '%s\n' "$ips" | grep -v '^$' | while IFS= read -r a; do
				printf ',"%s"' "$(jsonesc "$a")"; done)
			ipjson="[${ipjson#,}]"
			if [ "$_first" = 1 ]; then _first=0; else printf ','; fi
			printf '{"mac":"%s","ip":"%s","ips":%s,"name":"%s","wan":"%s","online":%s}' \
				"$mac" "$(jsonesc "$ip")" "$ipjson" "$(jsonesc "$n")" "$w" "$on"
		done
	}
	printf ']}'
	;;

# ---- HTML shell --------------------------------------------------------------
*)
	printf 'Content-Type: text/html; charset=utf-8\r\n\r\n'
	cat <<'HTML'
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NexusGate</title>
<style>
:root{--bg:#0b1020;--card:#141b31;--edge:#232c4d;--txt:#e6ecff;--dim:#8b96b8;
--ok:#3ddc84;--bad:#ff5470;--v:#4da3ff;--c:#ffb84d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:14px/1.45 -apple-system,system-ui,sans-serif}
header{display:flex;align-items:center;gap:16px;padding:10px 16px;
background:var(--card);border-bottom:1px solid var(--edge)}
header h1{font-size:16px;margin:0}
nav button{background:none;border:none;color:var(--dim);padding:8px 12px;
cursor:pointer;font-size:14px;border-bottom:2px solid transparent}
nav button.on{color:var(--txt);border-color:var(--v)}
.tab{display:none;padding:12px}.tab.on{display:block}
iframe{width:100%;height:calc(100vh - 70px);border:0;background:#fff;border-radius:8px}
.cards{display:flex;gap:12px;flex-wrap:wrap}
.card{background:var(--card);border:1px solid var(--edge);border-radius:10px;
padding:12px 16px;min-width:240px;flex:1}
.card h2{margin:0 0 6px;font-size:15px}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px}
.pill.up{background:rgba(61,220,132,.15);color:var(--ok)}
.pill.down{background:rgba(255,84,112,.15);color:var(--bad)}
.kv{color:var(--dim);font-size:13px}.kv b{color:var(--txt);font-weight:500}
pre#logs{background:var(--card);border:1px solid var(--edge);border-radius:10px;
padding:10px;max-height:50vh;overflow:auto;font-size:12px;white-space:pre-wrap}
svg{width:100%;background:var(--card);border:1px solid var(--edge);border-radius:10px}
text{fill:var(--txt);font-size:12px}.dimt{fill:var(--dim);font-size:11px}
.grp{min-width:260px;flex:1}
.grp .row{display:flex;gap:8px;align-items:baseline;padding:3px 0;border-bottom:1px solid var(--edge)}
.grp .row:last-child{border-bottom:0}
.grp .dot{width:8px;height:8px;border-radius:50%;background:var(--ok);flex:none;align-self:center}
.grp.v .dot{background:var(--v)}.grp.c .dot{background:var(--c)}
.row.off .dot{background:#3a4569}.row.off .nm{color:var(--dim)}
.nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meta{color:var(--dim);font-size:11px;margin-left:auto;white-space:nowrap}
</style></head><body>
<header><h1>NexusGate</h1><nav>
<button data-t="aff" class="on">Devices</button>
<button data-t="stats">WAN Stats</button>
<button data-t="topo">Topology</button>
</nav></header>
<div id="aff" class="tab on"><iframe src="/cgi-bin/wan-affinity"></iframe></div>
<div id="stats" class="tab"><div class="cards" id="wancards"></div>
<h3>Recent WAN log</h3><pre id="logs">loading…</pre></div>
<div id="topo" class="tab"><svg id="svg" height="190"></svg>
<div class="cards" id="groups"></div></div>
<script>
var prev=null, statTimer=null;
document.querySelectorAll('nav button').forEach(function(b){
  b.onclick=function(){
    document.querySelectorAll('nav button').forEach(function(x){x.classList.remove('on')});
    document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('on')});
    b.classList.add('on');document.getElementById(b.dataset.t).classList.add('on');
    if(b.dataset.t==='stats'){loadStats();statTimer=setInterval(loadStats,5000);}
    else if(statTimer){clearInterval(statTimer);statTimer=null;}
    if(b.dataset.t==='topo')loadTopo();
  };
});
function fmtB(n){var u=['B','KB','MB','GB','TB'],i=0;n=+n;
  while(n>=1024&&i<4){n/=1024;i++}return n.toFixed(i?1:0)+' '+u[i];}
// All API-derived strings (names, labels, lease/OUI data) are client-controlled:
// render exclusively via createElement/textContent (no HTML string assembly).
function el(tag,cls,txt){var e=document.createElement(tag);
  if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e;}
function kv(t){return el('div','kv',t);}
function loadStats(){
 fetch('?api=stats').then(function(r){return r.json()}).then(function(d){
  var wrap=document.getElementById('wancards');wrap.textContent='';
  d.wans.forEach(function(w){
   var c=el('div','card');
   var h=el('h2',null,w.label+' ');
   h.appendChild(el('span','pill '+(w.up?'up':'down'),w.up?'UP':'DOWN'));
   c.appendChild(h);
   c.appendChild(kv('dev '+(w.dev||'\u2014')+' \u00b7 gw '+(w.gw||'\u2014')));
   c.appendChild(kv('rx '+fmtB(w.rx_bytes)+' \u00b7 tx '+fmtB(w.tx_bytes)));
   if(prev&&prev.ts<d.ts){var dt=d.ts-prev.ts,p=prev.wans.find(function(x){return x.key===w.key});
    if(p&&dt>0)c.appendChild(kv('\u2193 '+fmtB((w.rx_bytes-p.rx_bytes)/dt)
      +'/s \u00b7 \u2191 '+fmtB((w.tx_bytes-p.tx_bytes)/dt)+'/s'));}
   wrap.appendChild(c);
  });
  document.getElementById('logs').textContent=d.logs.join('\n')||'(no matching log lines)';
  prev=d;
 }).catch(function(e){document.getElementById('logs').textContent='stats fetch failed: '+e;});
}
function svgEl(n,at){var e=document.createElementNS('http://www.w3.org/2000/svg',n);
  for(var k in at)e.setAttribute(k,at[k]);return e;}
function drawSpine(w1,w2){
 var s=document.getElementById('svg');while(s.firstChild)s.removeChild(s.firstChild);
 var W=s.clientWidth||900,cx=W/2;
 function ln(x1,y1,x2,y2,col,dash){var l=svgEl('line',{x1:x1,y1:y1,x2:x2,y2:y2,
   stroke:col,'stroke-width':1.5});if(dash)l.setAttribute('stroke-dasharray','4 3');
   s.appendChild(l);}
 function nd(x,y,r,col,label,sub){s.appendChild(svgEl('circle',{cx:x,cy:y,r:r,fill:col}));
   var t=svgEl('text',{x:x+r+6,y:y+4});t.textContent=label;s.appendChild(t);
   if(sub){var u=svgEl('text',{x:x+r+6,y:y+18,'class':'dimt'});u.textContent=sub;s.appendChild(u);}}
 ln(cx,30,cx-140,95,w1.up?'#3ddc84':'#ff5470',!w1.up);
 ln(cx,30,cx+140,95,w2.up?'#3ddc84':'#ff5470',!w2.up);
 ln(cx-140,95,cx,160,'#4da3ff');ln(cx+140,95,cx,160,'#ffb84d');
 nd(cx,30,9,'#8b96b8','Internet','');
 nd(cx-140,95,8,w1.up?'#3ddc84':'#ff5470',w1.label,(w1.dev||'')+' '+(w1.gw||''));
 nd(cx+140,95,8,w2.up?'#3ddc84':'#ff5470',w2.label,(w2.dev||'')+' '+(w2.gw||''));
 nd(cx,160,9,'#e6ecff','NexusGate','br-lan');
}
function loadTopo(){
 fetch('?api=topology').then(function(r){return r.json()}).then(function(d){
  var w1=d.wans[0],w2=d.wans[1];
  drawSpine(w1,w2);
  var devs=d.devices.slice().sort(function(a,b){return (b.online-a.online)||
    (a.name||a.mac).localeCompare(b.name||b.mac)});
  var groups=[{k:'v',t:w1.label+' (WAN1)',cls:'v'},
              {k:'c',t:w2.label+' (WAN2)',cls:'c'},
              {k:'',t:'Default route',cls:''}];
  var wrap=document.getElementById('groups');wrap.textContent='';
  groups.forEach(function(gr){
   var list=devs.filter(function(x){return (x.wan||'')===gr.k});
   var c=el('div','card grp'+(gr.cls?' '+gr.cls:''));
   c.appendChild(el('h2',null,'\u2192 '+gr.t+' \u00b7 '+list.length));
   list.forEach(function(dv){
    var r=el('div','row'+(dv.online?'':' off'));
    r.appendChild(el('span','dot'));
    r.appendChild(el('span','nm',dv.name||dv.mac));
    r.appendChild(el('span','meta',((dv.ips&&dv.ips.length?dv.ips:dv.ip?[dv.ip]:[]).join(', ')+' \u00b7 ').replace(/^ \u00b7 $/,'')+dv.mac));
    c.appendChild(r);
   });
   if(!list.length)c.appendChild(kv('(none)'));
   wrap.appendChild(c);
  });
 }).catch(function(e){document.getElementById('groups').textContent=
   'topology fetch failed: '+e;});
}
</script></body></html>
HTML
	;;
esac
