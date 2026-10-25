# Application dependencies and startup

The application in `app/` was copied from the working Pi on 2026-10-25. Git commit `88a40b9` preserves the unmodified import; [pi-app-snapshot.json](pi-app-snapshot.json) records those original eight source-file hashes, not the hashes of later revisions. Earlier experiments and alternate program versions elsewhere in `/home/ben` remain separate from the selected application.

## Layout and execution

The Pi currently keeps `app.py`, all selected display scripts, and the `templates/` directory directly in `/home/ben`. This repository groups those same files under `app/`.

`app.py` starts subprocesses using relative filenames such as `clock.py` and `clear_screen.py`. Its working directory must therefore contain those files. For this repository's layout, the equivalent manual invocation on a prepared Pi is:

```bash
cd /path/to/garching-board/app
python3 app.py
```

Do not start a second controller or display program while another process owns the matrices. The controller, clock, visualizer, Pong, Falling Sand, Drawing Harmonograph, and Acid Rain defer hardware initialization until execution so tests can import them safely. The other original display programs still initialize SPI at import and must not be imported for an ordinary desktop syntax check.

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

Visualizer and Pong target 25 frames per second with a monotonic deadline that includes rendering and SPI time. An overrun resets the schedule without a burst of catch-up frames. The spectrum chooses new targets at eight updates per second and interpolates its bar heights using elapsed time, so higher rendering rates do not make its motion frantic. Pong advances one physics step per rendered frame, with a horizontal ball speed of 1.2 pixels per step and explosion gravity of 0.10 pixels per step squared. Debris launches inward at 0.2–0.5 pixels per step to keep the fragments near the paddle. The startup IP message scrolls at 12 pixels per second.

The clock uses the original CP437 font and 16-pixel stretch. Every digit has an eight-pixel cell, matching the widest digit; each colon has a three-pixel cell. This keeps the entire clock 54 pixels wide, centered at x=5, with fixed separator positions as the time changes. It writes only when `HH:MM:SS` changes, sleeping until the next wall-clock second.

Falling Sand, Drawing Harmonograph, and Acid Rain run through `effect_runner.py` at a target of 20 FPS, using the same mapping and contrast 16. Each renderer uses elapsed time and bounded state. A terminated effect clears the board before the next program starts.

Falling Sand starts empty and releases eighteen grains per second. Each grain chooses one of three evenly spaced, five-pixel-wide drop areas and a random position inside it. Grains fall downward and slide diagonally around obstacles, building uneven piles. Backed-up inlets spill into the nearest open top position so the screen can fill all 1,024 pixels, including the corners. The full image remains visible briefly before a two-pixel opening appears at the bottom centre. Pouring pauses while the opening widens by one pixel on each side every third of a second, reaching the entire bottom width. The plug closes only when the display is empty, then pouring resumes. A full container drains in about 10.5 seconds. Gravity always points downward.

Sand movement uses a compact occupancy bitmask and simultaneous moves into cells that were empty at the start of each step. This prevents vacancies from pulling a whole row or column across the display in one update. Destination claims prevent colliding grains from merging. Filling advances at 18 steps per second and drainage at 36, with at most six simulation steps per render call. Images are built directly from packed bits; the byte-grid property is a fixture/debug snapshot outside the rendering path.

Drawing Harmonograph keeps the selected trajectory and a tail capped at 180 samples. Acid Rain uses sixteen staggered, single-column pixel trails at 6–14 pixels per second, with two-pixel heads and dotted tails. Each trail falls through the bottom and recycles above the display after its tail exits. These three modes are directly available in the main controller; the temporary preview dashboard and rejected studies have been removed.

## Weather and messages

The controller's **Everyday** section contains Clock, Bus Timetable, and Weather. The separate message form selects Message Board when submitted; the animations are grouped under **Visualizers**. Selection remains manual. The controller still owns one display subprocess at a time.

Weather cycles through current temperature and conditions, feels-like temperature and wind, today's high, today's low, today's precipitation chance and amount, and the next six hourly forecasts. Current, feels-like, high, and low temperatures include Celsius and Fahrenheit. Hourly cards show Celsius, precipitation probability, and millimetres. `TMR` marks hours after midnight. Feels-like temperature and wind provide context for choosing clothing; the display does not make a personal jacket recommendation. Each card stays for at least four seconds and allows longer rows to finish scrolling.

Forecasts come from the [Open-Meteo Forecast API](https://open-meteo.com/en/docs), using Europe/Berlin local dates and Unix timestamps across daylight-saving changes. The default location is Garching at approximately 48.25° N, 11.65° E. Set `GARCHING_WEATHER_LATITUDE` and `GARCHING_WEATHER_LONGITUDE` in the controller's environment to override it. Pi OS supplies the IANA timezone database; a Windows development environment may need `tzdata` or an injected timezone in hardware-free previews. No runtime dependency has been added.

Fetching runs in a background thread every ten minutes, with an eight-second request timeout and a one-minute retry after failure. Missing measurements show `--`. A failed refresh or data at least twenty minutes old marks cards `OLD`; data at least two hours old is replaced with `WEATHER / UNAVAILABLE`. Initial requests show `LOADING`. Cached daily values are selected by their local date, so yesterday's high and low are not labelled as today's.

Messages accept up to 280 characters across two lines. Short lines stay still; long lines scroll at twelve pixels per second with a two-second pause at each end. Latin accents and German umlauts are transliterated to the matrix font, while unsupported characters such as emoji are rejected. Invalid submissions keep the current mode running and show an error beside the form. Text is passed as a subprocess argument and is never executed as a shell command. The last submitted message remains in controller memory until restart; messages are not saved to disk.

`matrix_text.py` shares text layout between both modes and caches glyph images so scrolling frames only crop pixels. Both new modes use `effect_runner.py` for matrix ownership, frame pacing, and clearing on exit. Deploy `weather.py`, `message.py`, and `matrix_text.py` alongside the updated controller and template in the existing flat `/home/ben` layout. Follow the staged tests and recovery procedure below before replacing live files.

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

The suite compares the bulk mapping with the original pixel loop, checks every logical pixel's location, verifies pacing through a fake clock, checks fixed clock-cell/separator positions and second-change redraws, checks spectrum interpolation independently of render rate, and exercises concurrent Flask requests with fake subprocesses. Visualization checks cover empty sand starts, randomized drop areas, collision and boundary handling, packed image output, full-screen fills, widening drainage with pouring paused, plug closure, repeated cycles, fixed rain tempo, continued motion, and bounded state/catch-up work. Pong checks cover ball speed, gravity, bouncing, and eventual settling.

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
