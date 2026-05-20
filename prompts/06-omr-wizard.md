# 06 Optional OMR Bonding Wizard

## Goal
Enable VPS-backed true bonding only if single-flow throughput above one WAN is required. Skip this step for normal SD-WAN deployments.

## Actions
1. Deploy VPS only if needed.
2. Run OMR wizard.
3. Keep gaming/VoIP bypass direct.

## Checkpoint
Optional MPTCP tunnel works; default load-balance mode remains available as fallback.
