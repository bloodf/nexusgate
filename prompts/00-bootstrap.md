# 00 Bootstrap

## Goal
Execute NexusGate step `bootstrap` safely on OpenMPTCProuter.

## Inputs
- Router IP: `10.25.0.1` unless changed
- WAN roles: eth1=wan1 (primary), eth2=wan2 (secondary); eth0+eth3 bridged to br-lan

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
