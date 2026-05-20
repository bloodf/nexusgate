#!/bin/sh
set -eu
ss -lntup | awk '{print}'
echo "Expected: 65001/udp 65101/tcp 65222/tcp 65500/tcp"
