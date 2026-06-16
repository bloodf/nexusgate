#!/bin/sh
# Intercept LAN DNS queries to 100.100.100.100 (Tailscale MagicDNS leftover)
# and DNAT them to the local resolver (dnsmasq -> AdGuard).
#
# Why: clients that were once on the tailnet keep 100.100.100.100 in their
# resolv.conf / static DNS config. After Tailscale is removed, those packets
# get routed to the public Internet, fall on the floor, and the client thinks
# DNS is broken. This rule transparently rewrites them to the router IP, so the
# client recovers without reconfiguration.
#
# Safe to leave in place permanently — 100.100.100.100 is Tailscale-only and
# never a legitimate destination from a non-tailnet host.

set -eu

ROUTER_IP=${ROUTER_IP:-10.25.0.1}
TAILSCALE_DNS=${TAILSCALE_DNS:-100.100.100.100}

for proto in udp tcp; do
	NAME="intercept-ts-dns-$proto"
	# Idempotent: drop any prior copy of this rule by name
	while uci -q get "firewall.$(uci show firewall | grep "name='$NAME'" | head -1 | cut -d. -f2 | cut -d= -f1)" >/dev/null 2>&1; do
		SEC=$(uci show firewall | grep "name='$NAME'" | head -1 | cut -d. -f2 | cut -d= -f1)
		[ -z "$SEC" ] && break
		uci -q delete "firewall.$SEC"
	done
	uci add firewall redirect
	uci set firewall.@redirect[-1].name="$NAME"
	uci set firewall.@redirect[-1].src='lan'
	uci set firewall.@redirect[-1].src_dip="$TAILSCALE_DNS"
	uci set firewall.@redirect[-1].src_dport='53'
	uci set firewall.@redirect[-1].dest='lan'
	uci set firewall.@redirect[-1].dest_ip="$ROUTER_IP"
	uci set firewall.@redirect[-1].dest_port='53'
	uci set firewall.@redirect[-1].proto="$proto"
	uci set firewall.@redirect[-1].target='DNAT'
done

uci commit firewall
/etc/init.d/firewall reload

echo
echo "== DNAT rules =="
nft list chain inet fw4 dstnat_lan 2>/dev/null | grep -i "$TAILSCALE_DNS" || echo "(none — check fw4 dstnat hook)"
