# Pi setup and handoff

Recorded on 2026-10-25 from the completed Wi-Fi troubleshooting session and Ben's original hardware handoff. The device details below describe the last verified state, not a fresh installation. The scripts and reference configs were curated from that session; exploratory probes, password prompts, logs, private keys, and exported Windows Wi-Fi profiles were excluded.

## Device and access

| Item | Last verified value |
| --- | --- |
| Hardware | Original Raspberry Pi Zero WH, ARMv6 (`armv6l`, Debian architecture `armhf`) |
| OS | Raspberry Pi OS / Raspbian GNU/Linux 13, trixie |
| Python | 3.13 |
| Hostname | `garching-board` |
| SSH user | `ben`, with passwordless `sudo -n` available |
| Wi-Fi MAC | `b8:27:eb:25:40:39`, already registered with HHG |
| Tailscale IPv4 | `100.111.233.84` |
| Tailscale DNS name | `garching-board.tail8d1185.ts.net` |
| Tailscale version at setup | 1.104.2 |
| SSH host key | ED25519, `SHA256:NDIQPO5Al3Tku5LuagLuvpY5ufR9EjTR7aFYj5Sv12I` |

Administration uses ordinary OpenSSH over Tailscale. Tailscale SSH was not enabled. Tailscale was enrolled with `--accept-dns=false --hostname=garching-board` so Wi-Fi DHCP remains responsible for DNS. It was installed from the official signed Raspbian trixie package repository; `tailscaled.service` is enabled.

A dedicated SSH key was explicitly approved and added to `ben`'s authorized keys. The private key remains outside this repository in the original troubleshooting workspace. This checkout's ignored `.local/access.ps1` references that existing key and `.local/pi-known-hosts` contains the previously verified public host key. No access grants were changed while creating the repository.

The HHG and hotspot IPv4 leases seen during setup were `10.151.13.51` and `10.123.226.104`. They are DHCP leases and may change; prefer the Tailscale address for administration. `.local` hostname discovery was unreliable during troubleshooting.

## Wi-Fi design

`wlan0` is managed by the packaged `wpa_supplicant@wlan0.service` and an interface-scoped `garching-dhcp.service` using the installed `dhcpcd` client. NetworkManager remains running but intentionally reports `wlan0` as unmanaged. Original NetworkManager/Netplan profiles were retained for recovery.

The change was approved after NetworkManager 1.52.1 offered newer WPA-EAP key-management modes that did not work with this original Zero W. An explicit `key_mgmt=WPA-EAP` configuration succeeded. Preserve that compatibility setting and certificate validation when changing networking.

| Network | Authentication | Priority |
| --- | --- | --- |
| `HHG-2.4GHz` | WPA2-Enterprise, PEAP with inner MSCHAPv2 | 100 |
| `FBI Van` | WPA2-Personal phone hotspot | 10 |

The original Zero W supports 2.4 GHz Wi-Fi. Keep the phone hotspot on 2.4 GHz when using it as fallback. The SSID and password must match the saved network.

HHG uses RSN/CCMP, `key_mgmt=WPA-EAP`, `ieee80211w=0`, `eap=PEAP`, and `phase2="auth=MSCHAPV2"`. Server validation uses:

- CA file: `/etc/NetworkManager/certs/hhg-ca.pem`.
- Exact server identity: `domain_match="hochschulhaus-garching.de"`.
- Captured CA SHA-256: `cc1613f87044907f5a60b446e959df9184ce09b6ec9a0eb0bc608cc484818616`.
- Captured EAP leaf SHA-1: `06BCFB0678F3A5C6D95650016A744B474EC7EFEC`, matched against the previously saved Windows profile pin before trusting the captured chain.

The captured certificate chain and hostname passed OpenSSL verification. The captured certificates expire on 2027-03-24; investigate a changed or expired certificate through a trusted source rather than disabling validation. The public HHG website uses a different certificate, so its HTTPS chain is not a substitute for the EAP CA.

`dhcpcd` supplies DNS through `/etc/resolv.conf`. NetworkManager DNS handling is disabled. `systemd-resolved` and `systemd-networkd` were not enabled for this setup. The DHCP config deliberately omits `persistent` so old addresses and routes are removed when switching networks; `nohook wpa_supplicant` prevents a second supplicant from starting.

## Installed files

| Pi path | Role |
| --- | --- |
| `/etc/wpa_supplicant/wpa_supplicant-wlan0.conf` | HHG and hotspot settings, including credentials; mode 0600, root-owned |
| `/etc/NetworkManager/certs/hhg-ca.pem` | Verified HHG authentication CA |
| `/etc/dhcpcd-wlan0.conf` | Interface-scoped DHCP and DNS settings |
| `/etc/systemd/system/garching-dhcp.service` | DHCP client service for `wlan0` |
| `/etc/systemd/system/wpa_supplicant@wlan0.service.d/10-garching.conf` | Ordering and restart behavior for the packaged supplicant service |
| `/etc/NetworkManager/conf.d/90-garching-wlan0-unmanaged.conf` | Relinquishes Wi-Fi and DNS ownership |

Credential-free reference versions live in [setup/network](../setup/network/README.md). They do not provision a new Pi on their own.

## Completed verification

- HHG authenticated, obtained a DHCP lease, and reached an HTTPS endpoint.
- Tailscale carried SSH while the laptop and Pi were on different underlying Wi-Fi networks.
- Temporarily disabling HHG in the live supplicant triggered automatic hotspot fallback. DHCP, DNS, internet access, and Tailscale SSH worked on the hotspot.
- Re-enabling HHG and reassociating returned to the preferred network.
- After reboot, the Pi selected HHG with both networks available. Wi-Fi, DHCP, and Tailscale services were enabled and running; HTTPS and SSH worked.
- Temporary recovery timers were disabled and archived after the reboot check passed.

Run `scripts/pi/check-network.sh` through `scripts/Invoke-Pi.ps1 -Root` for a current read-only check. A failing check stops at the failed command; it does not attempt repair or expose saved credentials.

## Recovery material

The Pi retains a root-only backup at `/root/codex-wifi-backup.XGYaPE`:

- `migration-prechange/`: original Netplan files, NetworkManager runtime profiles, NetworkManager config, and `resolv.conf`.
- `rollback-networking.sh`: device-specific recovery back to NetworkManager and the saved hotspot profile.
- `recovery-units/`: archived `garching-network-recovery.service` and `.timer`.

The recovery timer is disabled and is not an ongoing watchdog. The original persistent profiles are in `/etc/netplan/90-NM-*.yaml`; NetworkManager generated runtime profiles under `/run/NetworkManager/system-connections/`.

The saved rollback script changes live network ownership and can interrupt SSH. Inspect its assumptions, confirm the hotspot is available, and arrange a timed recovery path before a future Wi-Fi migration. It is retained on the Pi as recovery material, not copied here as a routine setup command.

The original Windows troubleshooting scripts and diagnostics remain in the previous chat workspace under `work/wifi-diagnostics`. The old key location is needed by this checkout until access is deliberately migrated to another protected location. Do not delete that workspace merely because this repository now exists.

## Existing display application

The application was subsequently found under `/home/ben` and imported into this repository's `app/` directory on 2026-10-25. Ben confirms that the board and its programs work. The controller uses Flask on port 5000 and launches Clock, Game of Life, Bus Timetable, Pong, Music Visualizer, or the clear-screen program. The selected sources already configure SPI, sixteen MAX7219 devices, and the 64×16 pixel mapping.

An existing user-crontab `@reboot` entry starts `/home/ben/app.py`; it is not a display systemd service. No Pi files, processes, or startup settings were changed during the import. See [application dependencies and startup](application.md) for the exact entry, installed dependency versions, and source snapshot details.

The selected bus program already fetches departures for Untere Straßäcker. U6 departures remain an optional addition against the original project goal. The earlier assumption that hardware setup and display software still needed to be implemented was incorrect.
