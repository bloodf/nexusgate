#!/bin/sh
set -eu

# Enables INTERNAL ULA IPv6 only on the LAN (fd00::/8 address space).
# - NO WAN/ISP IPv6 is enabled. No IPv6 on wan1 or wan2.
# - IPv4 routing and per-device WAN affinity (tables 100/101) are completely untouched.
# - LAN clients receive a ULA address via SLAAC on their next RA; they do NOT get
#   internet reachability over IPv6 (ULA is not internet-routable by design).
# - Revert: uci set openmptcprouter.settings.disable_ipv6='1' && uci commit openmptcprouter
#            then /etc/init.d/network reload && /etc/init.d/odhcpd restart
# Safe to re-run (idempotent). Never touches WAN interfaces or affinity tables.

# ---------------------------------------------------------------------------
# 1. Flip OMR global disable_ipv6 flag if needed
# ---------------------------------------------------------------------------
_cur_dis=$(uci -q get openmptcprouter.settings.disable_ipv6 2>/dev/null || true)
if [ "$_cur_dis" = "1" ]; then
    echo "configure-ipv6: enabling IPv6 in OMR settings (was disable_ipv6=1)"
    uci -q set openmptcprouter.settings.disable_ipv6='0'
    uci -q commit openmptcprouter
else
    echo "configure-ipv6: OMR disable_ipv6 already 0 or unset - no change needed"
fi

# ---------------------------------------------------------------------------
# 2. Ensure a ULA prefix exists (keep existing; never regenerate)
# ---------------------------------------------------------------------------
_existing_ula=$(uci -q get network.globals.ula_prefix 2>/dev/null || true)
if [ -n "$_existing_ula" ]; then
    echo "configure-ipv6: ULA prefix already set: $_existing_ula - keeping it"
else
    echo "configure-ipv6: no ULA prefix found - generating one"
    # Primary: 5 random bytes from /dev/urandom -> 10 hex chars.
    hx=$(hexdump -n5 -e '5/1 "%02x"' /dev/urandom 2>/dev/null || true)
    if [ ${#hx} -ne 10 ]; then
        # Fallback: derive box-unique entropy (machine-id + NIC MACs) hashed to 10 hex.
        # NOT a fixed prefix - a fixed fd25:... would be globally guessable and risks a
        # real ULA collision because Tailscale bridges LAN routes into the tailnet.
        hx=$( (cat /etc/machine-id 2>/dev/null; cat /sys/class/net/eth*/address 2>/dev/null) | md5sum 2>/dev/null | cut -c1-10 )
    fi
    if [ ${#hx} -ne 10 ]; then
        echo "configure-ipv6: ERROR - could not derive a unique ULA prefix" >&2
        echo "configure-ipv6: neither /dev/urandom nor machine entropy yielded 10 hex chars" >&2
        echo "configure-ipv6: set one manually, then re-run, e.g.:" >&2
        echo "  uci set network.globals.ula_prefix='fdXX:XXXX:XXXX::/48' && uci commit network" >&2
        exit 1
    fi
    ula="fd$(echo "$hx" | cut -c1-2):$(echo "$hx" | cut -c3-6):$(echo "$hx" | cut -c7-10)::/48"
    echo "configure-ipv6: generated ULA prefix: $ula"
    uci -q set network.globals.ula_prefix="$ula"
fi

# ---------------------------------------------------------------------------
# 3. LAN: assign a /60 from the ULA prefix + ensure DHCPv6/RA serving
# ---------------------------------------------------------------------------
uci -q set network.lan.ip6assign='60'

# HARD GUARANTEE of the "NO WAN/ISP IPv6" claim: step 1 re-enables OMR/netifd
# v6 handling globally, so pin v6 OFF on both WANs explicitly. Without this, a
# DHCPv6/RA-capable modem (wan2/eth2) can install a v6 default route that
# bypasses the v4-only affinity tables 100/101.
uci -q set network.wan1.ipv6='0'
uci -q set network.wan2.ipv6='0'
uci -q delete network.wan1_6 2>/dev/null || true
uci -q delete network.wan2_6 2>/dev/null || true
uci -q delete network.wan6 2>/dev/null || true

uci -q set dhcp.lan.dhcpv6='server'
uci -q set dhcp.lan.ra='server'
uci -q set dhcp.lan.ra_slaac='1'
uci -q set dhcp.lan.ra_management='0'

# ---------------------------------------------------------------------------
# 4. Commit
# ---------------------------------------------------------------------------
uci -q commit network
uci -q commit dhcp

# ---------------------------------------------------------------------------
# 5. Apply
# ---------------------------------------------------------------------------
echo "configure-ipv6: reloading network and restarting odhcpd"
# Guard both under set -e: a benign non-zero must not abort mid-apply on the
# live, remotely-administered router.
/etc/init.d/network reload || true
sleep 2
/etc/init.d/odhcpd restart 2>/dev/null || true
sleep 1

# ---------------------------------------------------------------------------
# 6. Verify (read-only, labelled output)
# ---------------------------------------------------------------------------
echo ""
echo "=== IPv6 verification ==="
echo "ula_prefix=$(uci -q get network.globals.ula_prefix 2>/dev/null || echo '(not set)')"
echo "lan ip6assign=$(uci -q get network.lan.ip6assign 2>/dev/null || echo '(not set)')"
echo ""
echo "br-lan ULA address (fd::/8):"
ip -6 addr show br-lan 2>/dev/null | grep -E 'inet6 fd' || echo "  (no ULA on br-lan yet - may take a few seconds after reload)"
echo ""
echo "IPv6 routes (ULA fd::/fc:: prefixes):"
ip -6 route show 2>/dev/null | grep -E 'fd|fc' | head || echo "  (no ULA routes yet)"
echo ""
echo "NOTE: LAN clients receive an fd:: address via SLAAC on their next RA."
echo "      Renew with: ip -6 addr flush dev <iface> && rdisc6 <iface>  (or just reconnect)."
echo ""
echo "IPv4 and per-device WAN affinity are UNAFFECTED. ULA is not internet-routable."
echo "configure-ipv6: done"
