# Application dependencies and startup

The application in `app/` was copied from the working Pi on 2026-10-25. Git commit `88a40b9` preserves the unmodified import; [pi-app-snapshot.json](pi-app-snapshot.json) records those original eight source-file hashes, not the hashes of later revisions. Earlier experiments and alternate program versions elsewhere in `/home/ben` remain separate from the selected application.

## Layout and execution

The Pi currently keeps `app.py`, all selected display scripts, and the `templates/` directory directly in `/home/ben`. This repository groups those same files under `app/`.

`app.py` starts subprocesses using relative filenames such as `clock.py` and `clear_screen.py`. Its working directory must therefore contain those files. For this repository's layout, the equivalent manual invocation on a prepared Pi is:

```bash
cd /path/to/garching-board/app
python3 app.py
```

Do not start a second controller or display program while another process owns the matrices. The controller, clock, visualizer, Falling Sand, Drawing Harmonograph, and Acid Rain defer hardware initialization until execution so tests can import them safely. The other original display programs still initialize SPI at import and must not be imported for an ordinary desktop syntax check.

The controller binds to `0.0.0.0:5000` with Flask debug mode disabled. At startup it tries to scroll its local IP address on the display. It then starts the web controller with the selected-program indicator set to OFF; there is no saved-mode restoration in the imported code. The page's `/run` POST route switches display programs.

The UI has no authentication in this snapshot. Its intended access is through the local network or the existing Tailscale connection. No router forwarding, public hosting, or authentication changes were made during import.

## Existing automatic startup

Ben's user crontab contains:

```cron
@reboot /usr/bin/python3 /home/ben/app.py >> /home/ben/flask_log.txt 2>&1 &
```

The relative child-script paths rely on the controller running from `/home/ben`, the user's home directory used by cron. The log is `/home/ben/flask_log.txt`. The running controller was observed in the `cron.service` process group. This startup provides a boot launch; the entry does not configure automatic restarts after a controller crash or log rotation.

For a future deployment at another path, update the working directory and startup entry together. Migrating to systemd is optional and has not been performed. A GitHub push does not deploy the application: deployment is a separate operation replacing the selected files under `/home/ben` and restarting the controller from that directory.

## Rendering and switching

Program switches hold a lock across child termination, clearing, spawning, and selection-state updates. If a child ignores termination, it is killed and reaped before another program starts. This prevents overlapping requests from leaving multiple programs driving the display.

`display_utils.map_serpentine` uses Pillow crop, rotation, and paste operations instead of Python per-pixel loops. The visualizer, clock, bus scroll, and startup IP message share it. Pong's sparse point drawing is retained.

Visualizer and Pong target 25 frames per second with a monotonic deadline that includes rendering and SPI time. An overrun resets the schedule without a burst of catch-up frames. The spectrum chooses new targets at eight updates per second and interpolates its bar heights using elapsed time, so higher rendering rates do not make its motion frantic. Pong still advances one physics step per rendered frame. The startup IP message scrolls at 12 pixels per second.

The clock uses the original CP437 font and 16-pixel stretch. Every digit has an eight-pixel cell, matching the widest digit; each colon has a three-pixel cell. This keeps the entire clock 54 pixels wide, centered at x=5, with fixed separator positions as the time changes. It writes only when `HH:MM:SS` changes, sleeping until the next wall-clock second.

Falling Sand, Drawing Harmonograph, and Acid Rain run through `effect_runner.py` at a target of 20 FPS, using the same mapping and contrast 16. Each renderer uses elapsed time and bounded state. A terminated effect clears the board before the next program starts.

Falling Sand starts empty. Three fixed, evenly spaced spouts each release six grains per second. Grains fall downward and slide diagonally around obstacles, building three piles. When all three inlets remain blocked after movement, the entire image slides downward one row per physics step while the spouts continue emitting. After sixteen shifts, every grain from the old pile has left the display; the newer grains still in flight begin accumulating on the floor again. Gravity always points downward. A cycle takes about 39 seconds with the default seed.

Drawing Harmonograph keeps the selected trajectory and a tail capped at 180 samples. Acid Rain uses small monochrome code glyphs in sixteen staggered lanes, with a denser leading symbol and sparser tails. The code falls through the bottom and recycles above the display after its tail exits. These three modes are directly available in the main controller; the temporary preview dashboard and rejected studies have been removed.

## Hardware-free tests

On the prepared Pi, the existing dependencies support:

```bash
python3 -B -m unittest discover -s tests -v
```

For a desktop test environment, install only the pure dependencies used by the tests. Avoid pulling GPIO drivers into a Windows environment:

```bash
python -m venv .local/test-venv
# Activate the environment using your shell's normal activation command.
python -m pip install Flask==3.1.1 Pillow==11.1.0
python -m pip install --no-deps luma.core==2.4.2
python -m unittest discover -s tests -v
```

The suite compares the bulk mapping with the original pixel loop, checks every logical pixel's location, verifies pacing through a fake clock, checks fixed clock-cell/separator positions and second-change redraws, checks spectrum interpolation independently of render rate, and exercises concurrent Flask requests with fake subprocesses. Visualization checks cover empty sand starts, three fixed spouts, downward physics, complete sliding drains with uninterrupted streams, repeated cycles, fixed rain tempo, continued motion, and bounded state/catch-up work.

## Deployment and recovery

Deployments keep the existing flat `/home/ben` layout and cron entry. Stage the release and run its tests before stopping the current controller. Save the current selection and back up every file being replaced, recording whether newly added helpers were previously absent. Backup directories use `/home/ben/.garching-board/backups/<timestamp>-<commit>/`.

Stop the selected program through the controller, stop the identified controller process, replace the prepared files, and restart `/usr/bin/python3 /home/ben/app.py` with `/home/ben` as its working directory and output appended to `flask_log.txt`. Verify HTTP access, single-child switching, all display modes, and restore the saved selection after testing. Wi-Fi and cron settings do not need to change.

If verification fails, stop the new controller and its display child, restore the backed-up files, remove only helpers recorded as previously absent, and restart the backed-up controller with the saved selection. Keep release hashes and test results with the backup so the deployed revision can be identified.

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
