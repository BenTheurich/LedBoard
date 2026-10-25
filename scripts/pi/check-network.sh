#!/bin/bash
# Read-only verification for the installed wpa_supplicant/dhcpcd stack.
set -euo pipefail

printf '\n=== Device and boot ===\n'
hostname
uptime
cat /proc/sys/kernel/random/boot_id

printf '\n=== Wi-Fi and DHCP services ===\n'
systemctl is-active wpa_supplicant@wlan0.service garching-dhcp.service tailscaled.service
systemctl is-enabled wpa_supplicant@wlan0.service garching-dhcp.service tailscaled.service

printf '\n=== Current wireless authentication ===\n'
/usr/sbin/wpa_cli -i wlan0 status |
    grep -E '^(ssid|bssid|wpa_state|key_mgmt|ip_address|address|eap_state|suppPortStatus)='

printf '\n=== DHCP address and route ===\n'
ip -4 address show dev wlan0
ip -4 route show dev wlan0

printf '\n=== DHCP-provided DNS ===\n'
grep -E '^(nameserver|search|domain) ' /etc/resolv.conf

printf '\n=== Administration address ===\n'
tailscale ip -4

printf '\n=== Internet HTTPS ===\n'
curl --fail --silent --show-error --max-time 15 --output /dev/null \
    --write-out 'HTTPS status: %{http_code}\n' \
    https://pkgs.tailscale.com/stable/raspbian/trixie.tailscale-keyring.list

printf '\n=== Recovery timers ===\n'
systemctl list-timers --all --no-pager 'garching-network-recovery.timer'
