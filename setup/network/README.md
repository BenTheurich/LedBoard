# Wi-Fi reference configuration

These files describe the working stack recorded on 2026-10-25. They contain no credentials and are not an installer. Creating this repository did not apply them to the Pi.

| Reference file | Installed path on the Pi |
| --- | --- |
| `wpa_supplicant-wlan0.conf.example` | `/etc/wpa_supplicant/wpa_supplicant-wlan0.conf` |
| `dhcpcd-wlan0.conf` | `/etc/dhcpcd-wlan0.conf` |
| `garching-dhcp.service` | `/etc/systemd/system/garching-dhcp.service` |
| `10-garching.conf` | `/etc/systemd/system/wpa_supplicant@wlan0.service.d/10-garching.conf` |
| `90-garching-wlan0-unmanaged.conf` | `/etc/NetworkManager/conf.d/90-garching-wlan0-unmanaged.conf` |

The supplicant example needs an HHG identity, HHG password, and hotspot PSK supplied privately on the device. The actual setup derived a 256-bit hotspot PSK inside the Pi rather than copying its passphrase into the working files. Keep the completed supplicant configuration root-owned with mode 0600. Do not commit it.

The verified CA file is not included. Preserve the trusted CA already installed on the Pi; validate the source and server identity before provisioning another device. See [Pi setup](../../docs/pi-setup.md) for the recorded fingerprints and setup reasoning.

For reprovisioning, inspect the installed package versions and service definitions first. Back up persistent Netplan profiles and DNS settings, prepare credentials and certificate validation privately, and establish a timed rollback before handing `wlan0` away from NetworkManager. The network transition and reboot tests require a deliberate maintenance step. They are not part of the read-only check.
