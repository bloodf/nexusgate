#!/bin/sh
set -eu
echo "Manual: unplug WAN1+WAN2; verify wan3 online: mwan3 status"
mwan3 status || true
