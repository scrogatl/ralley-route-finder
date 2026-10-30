# SNAFU rally route planner

Finds a high-scoring route through the SNAFU rally bonus locations, using
driving distances and times from the Google Maps Directions API.

## Setup

Requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Steps 4 and up call the Google Maps API, which needs an API key in the
environment:

```bash
export GMAPS_API_KEY=your-key-here
```

Each rally year's input files (the bonus CSV and the GPX file from the rally
book) live in their own folder, e.g. `SNAFU_2026/`.

## Directions

1. ### Create combined csv with bonus, lat, lon, points and state

    Uses the lat/lon from the GPX file (the lat/lon in the CSV may be wrong) and
    the points from the CSV. Always writes `bonus-lat-lon-points.csv` in the
    current directory, overwriting any previous one.

    ```bash
    python extractDatafromGPX.py "SNAFU_2026/2026 SNAFU Bonus_Code-Lat-Long-Points_CSV - Rev E.csv" "SNAFU_2026/SNAFU 2026 - MASTER cao 11 Aug 26.gpx"
    ```

    The GPX must have a waypoint with "Rally" in its name (e.g. `Rally HQ
    Warner Robins`); the script stops without writing anything if it doesn't.
    That Rally HQ row always uses the GPX coordinates and 0 points, whatever
    the CSV says. Any other waypoint with no matching code in the CSV
    is printed as a warning and written with `ERROR` in place of its points;
    fix those before continuing.

2. ### Create a list of combinations

    Builds every ordered pair of bonuses from the file made in step 1.

    Output is `bonus1, bonus2, latlon1, latlon2, points at destination`

    ```bash
    python generateCombinationsFile.py bonus-lat-lon-points.csv combos.csv
    ```

3. ### Add the combos to a persistent queue

    This helps save $$$. It puts the combinations on a local, persistent queue
    (`path_to_queue/`), so if step 4 is interrupted it can be restarted without
    re-running anything already sent to Google's API.

    The queue keeps whatever was already in it, so empty it first if it holds
    pairs from an earlier run:

    ```bash
    python emptyQueue.py
    python enqueueCSV.py combos.csv
    ```

4. ### Read from queue and query Google API, storing results in csv

    **NOTE: This costs about $300 to run!!!!**

    Prints the queue size and waits for Enter before calling the API. Results
    are appended to the output file, so start with a fresh file for a new year.

    ```bash
    python getDirections.py segments.csv
    ```

5. ### Search all segments for best route

    Also reads `bonus-lat-lon-points.csv` from step 1 to look up each bonus's
    state.

    ```bash
    python searchSegments.py segments.csv
    ```

## Quick route plan without the Google API

`planRoute.py` plans a route using only the file made in step 1, so it's free.
Run it after step 1; steps 2–5 aren't needed. It searches thoroughly, so
it can take a few minutes; it uses all CPU cores and shows its progress
while it runs.

It estimates distances as straight-line miles between bonuses, and time as
distance ÷ average speed, plus a stop at each bonus to take its picture and a
gas stop every 175 miles. Driving through Atlanta (inside I-285 plus about 5
miles) is slowed to 25 MPH. The
route starts and ends at Rally HQ and fits in the time budget. It prints each
stop in order with leg miles, running hours and running score.

It also writes the route as a GPX file (`route.gpx` unless `--gpx` names
another) for Garmin BaseCamp and GPS units. The file has a waypoint for each
stop and a route through them in order, from Rally HQ back to Rally HQ. Each
point's comment holds its point value, and its description gives the stop
number, state and planned time.

```bash
python planRoute.py                       # reads bonus-lat-lon-points.csv
python planRoute.py --hours 8 --speed 50  # different time budget and speed
```

It only uses Python's standard library, so it also runs under
[PyPy](https://pypy.org), a faster Python, with the same results. A full
run takes about 20 seconds with PyPy versus 2½ minutes with regular Python.
To set it up (no install or admin rights needed):

```bash
mkdir -p ~/local/pypy && cd ~/local/pypy
curl -LO https://downloads.python.org/pypy/pypy3.11-v7.3.20-linux64.tar.bz2
tar xjf pypy3.11-v7.3.20-linux64.tar.bz2 && rm pypy3.11-v7.3.20-linux64.tar.bz2
cd -   # back to this folder
~/local/pypy/pypy3.11-v7.3.20-linux64/bin/pypy3 planRoute.py
```

`planRouteExact.py` needs regular Python, because OR-Tools doesn't support
PyPy.

| Option | Default | Meaning |
| --- | --- | --- |
| `--hours` | 9.5 | Time budget, Rally HQ to Rally HQ |
| `--speed` | 45 | Average speed in MPH |
| `--stop-minutes` | 5 | Time at each bonus to take its picture |
| `--road-factor` | 1.0 | Multiplies straight-line miles to approximate road miles (try 1.3) |
| `--gas-miles` | 175 | Stop for gas each time the route passes another this many miles; 0 for none |
| `--gas-minutes` | 10 | Time for each gas stop |
| `--slow-zone` | Atlanta | `LAT,LON,RADIUS_MILES,MPH`: the part of any leg inside this circle goes at MPH. Repeat for more zones; the default is `33.78,-84.39,15,25` |
| `--no-slow-zone` | | Turn off the default Atlanta slow zone |
| `--max-drop` | 6 | Longest run of stops the search tries removing at once; higher is slower |
| `--front-load` | 0 | Favor collecting points early, in case the day is cut short (see below) |
| `--workers` | all cores | How many CPU cores to search with |
| `--gpx` | route.gpx | Where to write the GPX file |

### Front-loading points

If something goes wrong on rally day, the points already collected are what
count, so it helps to bank the big bonuses early. With `--front-load`, each
bonus counts as its points × (1 + front-load × fraction of the day left when
you arrive):

- `0` finds the highest total, then orders the stops to collect points as
  early as the time budget allows.
- `1` makes a bonus at the start of the day worth up to twice one at the end,
  so the search will give up some total points to bank points sooner.
- Higher values lean further toward early points.

The output ends with a `Banked:` line showing the points collected by a
quarter, half and three quarters of the way through the day. Compare that
line across a few `--front-load` values to choose one.

## Provably best route

`planRouteExact.py` uses the same assumptions and prints the same table and
GPX file (`route-exact.gpx` by default), but solves the problem exactly with
Google's free [OR-Tools](https://developers.google.com/optimization) CP-SAT
solver. It runs locally, with no Google API calls and no cost.

```bash
python planRouteExact.py                       # reads bonus-lat-lon-points.csv
python planRouteExact.py --hours 8 --time-limit 1800
```

It ends with one of:

- `PROVEN OPTIMAL`: no route scores more under these assumptions.
- `NOT PROVEN`: it hit `--time-limit` (600 seconds by default) first. It
  prints the best route found and the most any route could score, so you know
  how much might be missing. Raise `--time-limit` to keep going.

It starts from `planRoute.py`'s best route, so it never reports a worse one.
Short days are proven quickly (4 hours takes seconds), but a full day with
all the bonuses is much harder: a 20-minute run on the 10-hour day stopped
with the best possible still up to 21% above the route found.

It takes the same options as `planRoute.py`, including gas stops and slow
zones, except `--front-load`; it only maximizes total points.

The search has no randomness, so the same inputs always give the same route.
It tries starting the route from every bonus and keeps the best result, but
it's still a heuristic, so it can't guarantee the very best route.
