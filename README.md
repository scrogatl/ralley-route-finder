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
