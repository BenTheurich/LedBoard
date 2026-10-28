# garching-board

A wall-mounted transit departure display for Garching, built with a Raspberry Pi Zero WH and MAX7219 LED matrices.

## Project status

The board is assembled and running. Its Flask controller, display programs, and HTML template were imported from the Pi on 2026-10-25, with source-file hashes checked during transfer. The current code adds serialized program switching, faster pixel mapping, paced animation frames, and a fixed-width clock that redraws only when the displayed second changes. The visualizer interpolates slower animation updates between frames. The original import remains recorded in [pi-app-snapshot.json](docs/pi-app-snapshot.json) and Git commit `88a40b9`.

Open the [controller](http://garching-board.local:5000/) on the local network. If local hostname discovery is unavailable, the controller is also reachable at `http://100.111.233.84:5000/` while connected to the same Tailscale network. It starts through the existing cron `@reboot` entry.

For browser-only access, open the [password-protected controller](https://garching-board.tail8d1185.ts.net/). Visitors enter the shared username and password; they do not need Tailscale installed or an account. Tailscale Funnel forwards HTTPS requests to the controller's authenticated loopback listener. Keep the shared login details private.

Wi-Fi prefers HHG and falls back to the phone hotspot. HHG access, hotspot fallback, and reconnection after reboot passed during the network setup session. See [Pi setup](docs/pi-setup.md) and [application dependencies and startup](docs/application.md).

## Hardware and intended display

- Original Raspberry Pi Zero WH, ARMv6, with a pre-soldered GPIO header. This is the original Zero W generation, not the Zero 2 W.
- 32 GB SanDisk microSD card running Raspberry Pi OS.
- 5 V / 3 A micro-USB power supply.
- Four Hailege MAX7219 4-in-1 boards: sixteen 8×8 matrices, intended to form a 64×16 display.
- Dupont jumper cables.

The installed programs use SPI bus 0, device 0, with `cascaded=16`, `block_orientation=-90`, and `rotate=0`. They map a logical 64×16 image to the physical 128×8 chain, reversing both axes for the lower row.

## Existing programs

| Controller button | Source | Behavior |
| --- | --- | --- |
| Clock | [clock.py](app/clock.py) | Stretched hours, minutes, and seconds in fixed-width digit cells |
| Game of Life | [game_of_life.py](app/game_of_life.py) | Cellular automaton |
| Bus Timetable | [my_bus_script3.py](app/my_bus_script3.py) | Two-row scrolling departures with day/night brightness |
| Weather | [weather.py](app/weather.py) | Four daily Celsius forecast points, plus labeled current conditions, high/low, and hourly rain screens |
| Message Board | [message.py](app/message.py) | Send up to two lines from the controller; long rows scroll horizontally |
| Pixel Drawing | [drawing.py](app/drawing.py) | Draw on the 64×16 grid using touch or a mouse, then send the image |
| Pong | [pong_explode2.py](app/pong_explode2.py) | Animated Pong with particle effects |
| Music Visualizer | [visualizations.py](app/visualizations.py) | Simulated spectrum bars; no audio input |
| Falling Sand | [falling_sand.py](app/falling_sand.py) | Three random drop areas fill the screen; pouring pauses while a central opening widens to drain it |
| Drawing Harmonograph | [harmonograph.py](app/harmonograph.py) | Looping trace with a gradually dotted tail |
| Acid Rain | [acid_rain.py](app/acid_rain.py) | Falling pixel trails that pass through the bottom |
| TURN OFF | [clear_screen.py](app/clear_screen.py) | Clears the matrix |

The bus program queries MVG through the Python `mvg` package for **Garching, Untere Straßäcker**, filtering lines **230**, **292**, and **X205** toward **Forschungszentrum**. It displays X205 as `205`. U6 departures at Garching-Forschungszentrum were part of the original goal and are not implemented in this selected program.

The controller groups Clock, Bus Timetable, and Weather under **Everyday**, gives messages and pixel drawings their own editors, and groups animations under **Visualizers**. Sending text or a drawing selects that mode immediately and keeps the draft available for editing. Modes stay selected until changed through the controller; no automatic mode switching is configured. These changes require deploying the source files before they appear on the Pi.

Weather uses [Open-Meteo](https://open-meteo.com/) without an API key. See [weather and messages](docs/application.md#weather-and-messages) for display pages, refresh behavior, and coordinates.

For access from other residents' devices, see [sharing access](docs/application.md#sharing-access). The `100.111.233.84` address requires Tailscale; connecting to HHG Wi-Fi alone does not provide access to that address.

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

- `app/`: the controller, nine display programs, shared rendering/timing helpers, and `templates/index.html`.
- `requirements.txt`: observed versions of the application's direct Python dependencies; native Pi dependencies are documented separately.
- `docs/application.md`: runtime versions, working-directory requirements, and the existing cron startup.
- `docs/pi-app-snapshot.json`: import timestamp, source paths, and SHA-256 hashes for the eight imported files.
- `scripts/Invoke-Pi.ps1`: SSH helper adapted from the Wi-Fi setup session, with configurable local key paths and strict host-key checking.
- `scripts/pi/check-network.sh`: read-only check adapted from the final persistent Wi-Fi verification script.
- `setup/network/`: credential-free reference files for the installed Wi-Fi stack. These are not an automatic installer.
- `docs/pi-setup.md`: device details, setup decisions, verification results, and recovery locations.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests require Flask, Pillow, and luma.core, and run without initializing GPIO or SPI. They verify concurrent switching, child cleanup, pixel mapping, frame pacing, clock redraws, repeated sand cycles, and bounded visualization state. See [application documentation](docs/application.md) for a desktop test environment and deployment notes.

## Possible next work

The hardware setup, pixel mapping, bus fetching, rendering, and controller startup already exist. Further work can focus on optional U6 departures and clearer handling of transit-data failures. Moving startup from cron to systemd would be an optional operational change.

The older Mbed `EmbeddedSnakeGame` project found on this PC is separate; its firmware has not been imported here.
