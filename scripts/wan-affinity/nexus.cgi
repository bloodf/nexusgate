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
	# LAN devices: dhcp leases merged with locked-but-offline MACs (same union
	# as wan-affinity.cgi so the two tabs never disagree on the device set).
	{
		[ -f "$LEASES" ] && awk '{print tolower($2)"|"$3"|"$4}' "$LEASES"
		for f in "$CLARO_LIST" "$VIVO_LIST"; do
			[ -f "$f" ] && sed 's/#.*//; s/[[:space:]]//g' "$f" | grep -v '^$' | \
				tr 'A-F' 'a-f' | sed 's/$/||/'
		done
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
			# reachability: neighbor table (no per-device pings; keeps API fast)
			on=0
			ip neigh show 2>/dev/null | grep -qi "lladdr $mac" && \
				ip neigh show 2>/dev/null | grep -i "lladdr $mac" | grep -qE 'REACHABLE|STALE|DELAY|PROBE' && on=1
			if [ "$_first" = 1 ]; then _first=0; else printf ','; fi
			printf '{"mac":"%s","ip":"%s","name":"%s","wan":"%s","online":%s}' \
				"$mac" "$(jsonesc "$ip")" "$(jsonesc "$n")" "$w" "$on"
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
</style></head><body>
<header><h1>NexusGate</h1><nav>
<button data-t="aff" class="on">Devices</button>
<button data-t="stats">WAN Stats</button>
<button data-t="topo">Topology</button>
</nav></header>
<div id="aff" class="tab on"><iframe src="/cgi-bin/wan-affinity"></iframe></div>
<div id="stats" class="tab"><div class="cards" id="wancards"></div>
<h3>Recent WAN log</h3><pre id="logs">loading…</pre></div>
<div id="topo" class="tab"><svg id="svg" height="560"></svg></div>
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
function loadStats(){
 fetch('?api=stats').then(function(r){return r.json()}).then(function(d){
  var h='';
  d.wans.forEach(function(w){
   var rate='';
   if(prev&&prev.ts<d.ts){var dt=d.ts-prev.ts,p=prev.wans.find(function(x){return x.key===w.key});
    if(p&&dt>0)rate='<div class="kv">&#8595; <b>'+fmtB((w.rx_bytes-p.rx_bytes)/dt)+'/s</b> '
      +'&#8593; <b>'+fmtB((w.tx_bytes-p.tx_bytes)/dt)+'/s</b></div>';}
   h+='<div class="card"><h2>'+esc(w.label)+' <span class="pill '+(w.up?'up':'down')+'">'
    +(w.up?'UP':'DOWN')+'</span></h2>'
    +'<div class="kv">dev <b>'+(w.dev?esc(w.dev):'—')+'</b> · gw <b>'+(w.gw?esc(w.gw):'—')+'</b></div>'
    +'<div class="kv">rx <b>'+fmtB(w.rx_bytes)+'</b> · tx <b>'+fmtB(w.tx_bytes)+'</b></div>'
    +rate+'</div>';
  });
  document.getElementById('wancards').innerHTML=h;
  document.getElementById('logs').textContent=d.logs.join('\n')||'(no matching log lines)';
  prev=d;
 }).catch(function(e){document.getElementById('logs').textContent='stats fetch failed: '+e;});
}
function loadTopo(){
 fetch('?api=topology').then(function(r){return r.json()}).then(function(d){
  var s=document.getElementById('svg'),W=s.clientWidth||900;
  var devs=d.devices.slice().sort(function(a,b){return (b.online-a.online)||
    (a.name||a.mac).localeCompare(b.name||b.mac)});
  var rows=Math.max(devs.length,1),H=Math.max(560,rows*26+180);s.setAttribute('height',H);
  var g='',cx=W/2;
  function line(x1,y1,x2,y2,col,dash){g+='<line x1="'+x1+'" y1="'+y1+'" x2="'+x2
    +'" y2="'+y2+'" stroke="'+col+'" stroke-width="1.5"'+(dash?' stroke-dasharray="4 3"':'')+'/>';}
  // label/sub MUST be pre-escaped by callers (esc()); node() concatenates into SVG markup.
  function node(x,y,r,col,label,sub){g+='<circle cx="'+x+'" cy="'+y+'" r="'+r
    +'" fill="'+col+'"/><text x="'+(x+r+6)+'" y="'+(y+4)+'">'+label+'</text>'
    +(sub?'<text x="'+(x+r+6)+'" y="'+(y+18)+'" class="dimt">'+sub+'</text>':'');}
  var iy=34,wy=100,ry=170;
  var w1=d.wans[0],w2=d.wans[1];
  line(cx,iy,cx-120,wy,w1.up?'#3ddc84':'#ff5470',!w1.up);
  line(cx,iy,cx+120,wy,w2.up?'#3ddc84':'#ff5470',!w2.up);
  line(cx-120,wy,cx,ry,'#4da3ff');line(cx+120,wy,cx,ry,'#ffb84d');
  var y0=ry+50;
  devs.forEach(function(dv,i){
    var y=y0+i*26,col=dv.wan==='c'?'#ffb84d':'#4da3ff';
    line(cx,ry,60,y,dv.online?col:'#232c4d',!dv.online);
    node(60,y,5,dv.online?col:'#3a4569',
      (dv.name?esc(dv.name):esc(dv.mac))+(dv.ip?' · '+esc(dv.ip):''),
      esc(dv.mac)+(dv.wan==='c'?' → '+esc(w2.label):dv.wan==='v'?' → '+esc(w1.label):' → default'));
  });
  node(cx,iy,9,'#8b96b8','Internet','');
  node(cx-120,wy,8,w1.up?'#3ddc84':'#ff5470',esc(w1.label),esc((w1.dev||'')+' '+(w1.gw||'')));
  node(cx+120,wy,8,w2.up?'#3ddc84':'#ff5470',esc(w2.label),esc((w2.dev||'')+' '+(w2.gw||'')));
  node(cx,ry,9,'#e6ecff','NexusGate','br-lan');
  s.innerHTML=g;
 }).catch(function(e){document.getElementById('svg').innerHTML=
   '<text x="20" y="30">topology fetch failed: '+esc(String(e))+'</text>';});
}
function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
</script></body></html>
HTML
	;;
esac
