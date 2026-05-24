#!/bin/sh
set -eu
echo "Manual: unplug WAN1 (eth1) or WAN2 (eth2); verify other survives in table 991337."
ip route show table 991337 || true
ip rule show | grep 991337 || true
