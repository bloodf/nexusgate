#!/bin/sh
set -eu
for h in 1.1.1.1 8.8.8.8; do ping -c 3 -W 1 "$h" >/dev/null && echo "$h ok" || echo "$h fail"; done
mwan3 status || true
