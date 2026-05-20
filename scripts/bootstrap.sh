#!/bin/sh
set -eu
echo "NexusGate hardware bootstrap"
command -v lspci >/dev/null 2>&1 && lspci | awk '/Ethernet|Network/{print}' || true
ip -o link show | awk -F': ' '{print $2}'
[ -b /dev/sda ] || [ -b /dev/nvme0n1 ] || echo "WARN: SSD block device not obvious"
