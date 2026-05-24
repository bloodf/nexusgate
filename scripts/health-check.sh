#!/bin/sh
set -eu
for h in 1.1.1.1 8.8.8.8; do ping -c 3 -W 1 "$h" >/dev/null && echo "$h ok" || echo "$h fail"; done
echo "--- ECMP table 991337 ---"
ip route show table 991337 || true
echo "--- ip rules 991337 ---"
ip rule show | grep 991337 || true
echo "--- multipath hash policy ---"
sysctl net.ipv4.fib_multipath_hash_policy || true
