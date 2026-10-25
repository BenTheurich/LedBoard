# Application dependencies and startup

The application in `app/` was copied from the working Pi on 2026-10-25. No source edits were made during import. The eight copied files are listed with their SHA-256 hashes in [pi-app-snapshot.json](pi-app-snapshot.json). Earlier experiments and alternate program versions elsewhere in `/home/ben` were left on the Pi.

## Layout and execution

The Pi currently keeps `app.py`, all selected display scripts, and the `templates/` directory directly in `/home/ben`. This repository groups those same files under `app/`.

`app.py` starts subprocesses using relative filenames such as `clock.py` and `clear_screen.py`. Its working directory must therefore contain those files. For this repository's layout, the equivalent manual invocation on a prepared Pi is:

```bash
cd /path/to/garching-board/app
python3 app.py
```

This is a reference command, not a deployment step performed during import. Do not start a second controller or display program while another process owns the matrices. Importing these modules can initialize SPI and write to the display, so they must not be imported for an ordinary desktop syntax check.

The controller binds to `0.0.0.0:5000` with Flask debug mode disabled. At startup it tries to scroll its local IP address on the display. It then starts the web controller with the selected-program indicator set to OFF; there is no saved-mode restoration in the imported code. The page's `/run` POST route switches display programs.

The UI has no authentication in this snapshot. Its intended access is through the local network or the existing Tailscale connection. No router forwarding, public hosting, or authentication changes were made during import.

## Existing automatic startup

Ben's user crontab contains:

```cron
@reboot /usr/bin/python3 /home/ben/app.py >> /home/ben/flask_log.txt 2>&1 &
```

The relative child-script paths rely on the controller running from `/home/ben`, the user's home directory used by cron. The log is `/home/ben/flask_log.txt`. The running controller was observed in the `cron.service` process group. This startup provides a boot launch; the entry does not configure automatic restarts after a controller crash or log rotation.

For a future deployment at another path, update the working directory and startup entry together. Migrating to systemd is optional and has not been performed. The GitHub push updates source control only; the Pi continues running its original `/home/ben` files.

## Observed runtime

The installed environment is Raspberry Pi OS / Raspbian 13 (trixie), ARMv6, with `/usr/bin/python3` version **3.13.5** and kernel **6.12.47+rpt-rpi-v6**.

The programs import these Python packages directly:

| Package | Observed version | Used for |
| --- | --- | --- |
| Flask | 3.1.1 | Controller and HTML rendering |
| luma.core | 2.4.2 | SPI interface, canvas, text, and fonts |
| luma.led-matrix | 1.7.0 | MAX7219 driver |
| Pillow | 11.1.0 | Images and drawing |
| mvg | 1.6.0 | Bus stop lookup and departures |

[requirements.txt](../requirements.txt) records those versions. It is an inventory of the working environment's direct application dependencies, not a complete lockfile or a verified clean-install recipe. The Pi has a mixture of Debian-provided packages and Python distribution metadata; native GPIO/SPI support and the ARMv6 OS are also required. Nothing was installed or upgraded during import.

Additional installed Python distribution versions relevant to the hardware and network stack were `spidev 3.6`, `rpi-lgpio 0.6`, `smbus2 0.4.3`, `requests 2.32.3`, and `aiohttp 3.13.2`. The application does not directly import an audio-capture or FFT package: Music Visualizer generates random spectrum bars.

The following installed Debian packages were queried from the Pi:

| Debian package | Observed package version |
| --- | --- |
| `python3-flask` | `3.1.1-1` |
| `python3-luma.core` | `2.4.2-1` |
| `python3-luma.led-matrix` | `1.7.0-1+b3` |
| `python3-pil` | `11.1.0-5` |
| `python3-spidev` | `3.6-1+b2` |
| `python3-lgpio` | `0.2.2-1~rpt1+trixie` |

Do not install a different GPIO backend over the working environment merely to satisfy a desktop dependency resolver. Future reprovisioning should preserve the selected Pi GPIO/SPI stack and verify access permissions before launching the application.

## Existing display and transit settings

The programs use SPI bus 0 / device 0 and initialize MAX7219 with sixteen cascaded devices, block orientation -90°, and rotation 0°. The logical image is 64×16. Its top 64×8 row maps directly to physical pixels 0–63; its bottom row maps to pixels 64–127 with both X and Y reversed.

`my_bus_script3.py` selects `Garching, Untere Straßäcker`, destination substring `Forschungszentrum`, and lines `230`, `292`, and `X205`. It shows at most eight matching departures and renders X205 as `205`. Day brightness is 32 from 07:00 until 20:00; night brightness is 10, using the Pi's local clock. It fetches another set of departures after each scrolling cycle. API exceptions and no matching departures both result in the current `No Bus Found` display, so the screen does not distinguish those cases.
