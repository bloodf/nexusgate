#!/bin/sh
set -eu
cp /opt/nexusgate/sysctl-performance.conf /etc/sysctl.d/99-nexusgate-performance.conf 2>/dev/null || true
sysctl --system || true
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do [ -w "$g" ] && echo performance > "$g" || true; done
swapoff -a || true
systemctl enable bpftune 2>/dev/null || true
systemctl start bpftune 2>/dev/null || true
echo "optimized"
