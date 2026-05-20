# Requirements

## Hardware

- Intel i3 mini-PC
- 16 GB RAM
- 4x Intel i226-V 2.5GbE
- SSD
- SIM/4G modem optional

## Software

- OpenMPTCProuter v0.63 x86_64 ext4 EFI or OpenWrt x86_64
- `mwan3`, `sqm-scripts`, LuCI addons from `scripts/install-luci-addons.sh`
- Optional: OMR VPS only for true bonding mode

## Network

- Two ISP WANs recommended
- VPS not required for default load balancing
- Optional VPS latency target <20ms if bonding enabled
