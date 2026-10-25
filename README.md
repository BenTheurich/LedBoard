# garching-board

A wall-mounted transit departure display for Garching, built with a Raspberry Pi Zero WH and MAX7219 LED matrices.

## Project status

The Pi's network setup is complete. It prefers HHG Wi-Fi, falls back to the phone hotspot, and is reachable through Tailscale. HHG access, hotspot fallback, and reconnection after reboot passed during the preceding setup session. The setup state was recorded on 2026-10-25; see [Pi setup](docs/pi-setup.md).

Display software has not been added to this repository. Matrix wiring, chain order, orientation, SPI availability, and the transit data source still need to be checked before implementing the display.

## Hardware and intended display

- Original Raspberry Pi Zero WH, ARMv6, with a pre-soldered GPIO header. This is the original Zero W generation, not the Zero 2 W.
- 32 GB SanDisk microSD card running Raspberry Pi OS.
- 5 V / 3 A micro-USB power supply.
- Four Hailege MAX7219 4-in-1 boards: sixteen 8×8 matrices, intended to form a 64×16 display.
- Dupont jumper cables.

The intended content is departures for buses **292** and **X205** at **Untere Straßäcker**, plus the **U6** at **Garching-Forschungszentrum**. Directions, walking-time cutoffs, and the screen layout have not been decided.

## Run a network check from Windows

The local checkout has an ignored `.local/access.ps1` that points to the existing SSH key and pinned host-key file. No keys or credentials are tracked by Git.

```powershell
. .\.local\access.ps1
& .\scripts\Invoke-Pi.ps1 -ScriptPath .\scripts\pi\check-network.sh -Root
```

This check reads connection state, service status, DHCP routing, DNS, and HTTPS availability. It does not change Wi-Fi or reboot the Pi. It requires the laptop to be connected to the same Tailscale network.

For another checkout, set these variables to your own authorized key and independently verified known-hosts file:

```powershell
$env:GARCHING_BOARD_SSH_KEY = 'C:\path\to\your\id_ed25519'
$env:GARCHING_BOARD_KNOWN_HOSTS = 'C:\path\to\your\pi-known-hosts'
```

The helper uses SSH user `ben`, address `100.111.233.84`, and host-key alias `garching-board.local` by default. `-PiAddress`, `-SshUser`, `-IdentityFile`, and `-KnownHostsFile` override those defaults. `-Root` runs the supplied script with `sudo -n`; use it only for a script you have reviewed.

## Repository contents

- `scripts/Invoke-Pi.ps1`: SSH helper adapted from the Wi-Fi setup session, with configurable local key paths and strict host-key checking.
- `scripts/pi/check-network.sh`: read-only check adapted from the final persistent Wi-Fi verification script.
- `setup/network/`: credential-free reference files for the installed Wi-Fi stack. These are not an automatic installer.
- `docs/pi-setup.md`: device details, setup decisions, verification results, and recovery locations.

## Next work

1. Confirm the physical wiring, power distribution, board arrangement, and chain order.
2. Check SPI and choose a display library that works on ARMv6.
3. Test a small pattern at low brightness and establish the 64×16 pixel mapping.
4. Verify stop identifiers and a suitable transit data source, then implement fetching and rendering.
5. Add startup through systemd and display behavior for stale or unavailable data.

The older Mbed `EmbeddedSnakeGame` project found on this PC is separate; its firmware has not been imported here.
