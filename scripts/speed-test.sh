#!/bin/sh
set -eu
command -v speedtest >/dev/null 2>&1 || { echo "Install speedtest-cli first"; exit 1; }
speedtest
