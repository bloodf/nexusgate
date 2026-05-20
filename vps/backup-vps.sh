#!/bin/sh
set -eu
tar czf /root/nexusgate-vps-backup-$(date +%F).tgz /root/openmptcprouter_config.txt /etc/shorewall /etc/ssh /etc/fail2ban 2>/dev/null || true
