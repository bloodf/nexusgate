# 12 Hardening

## Goal
Execute NexusGate step `hardening` safely on OpenMPTCProuter.

## Inputs
- Router IP: `192.168.100.1` unless changed
- WAN roles: eth0=wan1, eth1=wan2, eth2=br-lan, eth3=mgmt, wwan0=wan3

## Actions
1. Review prerequisites.
2. Run matching script/config if present.
3. Capture command output.
4. Apply config only after backup.

## Verification
- Command exits 0.
- UCI/config state matches expected role.
- Service restart succeeds.
- Checkpoint documented before next prompt.

## Rollback
Restore `/etc/config/*` backups created before this step.
