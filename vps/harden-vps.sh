#!/bin/sh
set -eu
install -d -m 700 /root/nexusgate-backup
[ -f /etc/ssh/sshd_config ] && cp /etc/ssh/sshd_config /root/nexusgate-backup/sshd_config.$(date +%s)
cat >/etc/ssh/sshd_config.d/99-nexusgate.conf <<'EOF'
Port 65222
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 20
X11Forwarding no
AllowTcpForwarding yes
EOF
chmod 600 /root/openmptcprouter_config.txt 2>/dev/null || true
command -v apt-get >/dev/null && apt-get update && apt-get install -y fail2ban unattended-upgrades auditd logrotate || true
cp /opt/nexusgate/fail2ban-jail.local /etc/fail2ban/jail.d/nexusgate.local 2>/dev/null || true
systemctl enable fail2ban unattended-upgrades auditd ssh || true
systemctl restart ssh fail2ban || true
echo "hardened"
