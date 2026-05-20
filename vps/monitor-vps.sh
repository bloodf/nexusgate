#!/bin/sh
set -eu
systemctl --no-pager --failed || true
ss -lntup | awk '/65001|65101|65222|65500/{print}' || true
