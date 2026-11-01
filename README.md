# SNAFU rally route planner

Finds a high-scoring route through the SNAFU rally bonus locations from
straight-line distances, then checks it on real roads with the Google Maps
Routes API.

## Setup

Requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Step 3 calls the Google Maps Routes API. It needs an API key from a Google
Cloud project with the **Routes API** turned on (Google Cloud console → APIs
& Services → Library → Routes API → Enable), set in the environment:

```bash
export GMAPS_API_KEY=your-key-here
```

Each rally year's input files (the bonus CSV and the GPX file from the rally
book) live in their own folder, e.g. `SNAFU_2026/`.

## Directions

1. ### Create combined csv with bonus, lat, lon, points, state and hours, and the combos

    Uses the lat/lon from the GPX file (the lat/lon in the CSV may be wrong) and
    the points from the CSV. Always writes `bonus-lat-lon-points.csv` in the
    current directory, overwriting any previous one.

    Give it the rally book PDF as well, and it also stores the hours each
    bonus is open. It reads each bonus's `Available:` line (`24 hours`, or
    e.g. `11:00 AM – 1:00 PM`) and adds two columns to the CSV: opening and
    closing time as 24-hour `HH:MM`, both blank for a bonus open 24 hours.
    The planners and `checkRoute.py` use them. It warns about any bonus it
    can't find hours for and treats it as open 24 hours, so check the
    warnings. Leave the PDF off and the CSV has no hours, as before.

    From the PDF's COMBINATION BONUSES section it also writes
    `bonus-combos.csv`, one line per combo: its code, its points, and the
    bonuses you need for it, e.g. `EAGLE, 3500, BISH GSUE STRU WJMS WWRD`. A
    combo's points come on top of its bonuses' own points, once you get every
    one of them. It lists the combos it found and warns about one with no
    points, no bonuses, or a bonus code that isn't in the CSV. The planners and
    `checkRoute.py` read it. Without the PDF it isn't written (an old one is
    left as it was).

    It also writes `bonus-lat-lon-points.gpx`, a copy of the rally's GPX file
    with each bonus's points after its name (e.g. `ABAC 510`) and at the
    front of its description (e.g. `510 points - Abraham Baldwin Agricultural
    College`), for loading into BaseCamp, a GPS or GPX Studio so the points
    show with each waypoint. A bonus with hours has them in its description
    too, and a bonus in a combo has the combo's code (e.g. `960 points, open
    11:00-13:00, EAGLE combo - ...`). Use it only for viewing: the planners read the
    CSV, and the renamed waypoints no longer match the bonus codes, so don't
    feed it back into this script. Each bonus's
    symbol is also a Garmin number showing its points in hundreds, so the big
    ones stand out on the map: a 630-point bonus shows a 6, and 900 points or
    more shows a 9. The number reads without relying on color; color only
    backs it up, blue under 500 points and red from 500 (no green, which is
    hard to tell from red with red-green color blindness). Garmin BaseCamp
    and GPS units show these symbols; GPX Studio doesn't support them and
    shows a plain marker, so there the name carries the points. To change the
    colors or where they switch, edit `HIGH_POINTS`, `LOW_COLOR` and
    `HIGH_COLOR` at the top of `extractDatafromGPX.py`. Everything else in the
    file is unchanged.

    ```bash
    python extractDatafromGPX.py "SNAFU_2026/2026 SNAFU Bonus_Code-Lat-Long-Points_CSV - Rev E.csv" "SNAFU_2026/SNAFU 2026 - MASTER cao 11 Aug 26.gpx" "SNAFU_2026/2026 SNAFU Rally Book Rev I.pdf"
    ```

    The GPX must have a waypoint with "Rally" in its name (e.g. `Rally HQ
    Warner Robins`); the script stops without writing anything if it doesn't.
    That Rally HQ row always uses the GPX coordinates and 0 points, whatever
    the CSV says. Any other waypoint with no matching code in the CSV
    is printed as a warning and written with `ERROR` in place of its points;
    fix those before continuing.

2. ### Plan the route

    Finds a high-scoring route from the file made in step 1, using
    straight-line distances, and writes it to a GPX file named with the
    date, time and points, e.g. `route-20261031-143005-11103pts.gpx`. It's free: no
    Google API calls. See [Planning the route](#planning-the-route) for the
    options.

    ```bash
    python planRoute.py
    ```

3. ### Check the route on real roads with Google Maps

    Sends the stops in the newest route GPX file to the Google Maps Routes API, in
    order, and shows the real road miles and driving times, and whether the
    day still fits. It is normally inside Google's free monthly usage. See
    [Checking the route with Google Maps](#checking-the-route-with-google-maps).

    ```bash
    python checkRoute.py --depart "2026-11-07 07:00"   # your rally's start time
    ```

    If it prints `OVER`, or the planned and real times differ a lot, plan
    again with the `--road-factor` and `--speed` it suggests, and check the
    new route.

## Planning the route

`planRoute.py` plans a route using only the file made in step 1, so it's free.
It searches thoroughly, so
it can take a few minutes; it uses all CPU cores and shows its progress
while it runs.

It estimates distances as straight-line miles between bonuses, and time as
distance ÷ average speed, plus a stop at each bonus to take its picture and a
gas stop every 175 miles. Driving through Atlanta (inside I-285 plus about 5
miles) is slowed to 25 MPH. The
route starts and ends at Rally HQ and fits in the time budget. It prints each
stop in order with leg miles, running hours, arrival time and running score.

**Bonus hours.** If the CSV has hours from the rally book (step 1), a route
only counts a bonus it reaches while it's open. It reaches one early only by
waiting there until it opens, and that wait comes out of the time budget; it
never reaches one after it closes. Hours are clock times, counted from the
rally start (`--start`, 7:00 by default, as in the 2026 rally book). The
table shows each bonus's hours and any wait, e.g. `waits 12 min to open at
11:00`. `--ignore-hours` plans as if every bonus were open all day, to see
what the hours cost. With the 2026 defaults, the hours cost 557 points:
10,546 instead of 11,103.

**Combos.** If `bonus-combos.csv` exists (step 1), a route that visits every
bonus in a combo also scores the combo's points. The table notes the stop that
completes one, e.g. `completes EAGLE combo +3500`, and the summary has a
`Combos:` line listing the combos scored and any only partly visited (which
score nothing extra). `--combos` names another file and `--ignore-combos`
plans without them.

On the 2026 map no combo is worth it in a one-day rally. EAGLE (3,500) needs
about 12¾ hours to visit just its 5 bonuses from Rally HQ and back, at the road factor and
speed Google's checks suggest (`--road-factor 1.22 --speed 46`), and BLACK and
ROSEN (2,000 each) about 11 hours, so none fits a 9½-hour day. CLOCK and MERCER
(500 each) fit, but cost more than they add: forcing MERCER into the best
route scores 8,292 instead of 8,667, and CLOCK 5,420. Checked with Google's
traffic, that MERCER route scores 7,636 and is back 36 minutes late. Even on straight-line
distances, BLACK, ROSEN and MERCER cost 4,200, 4,400 and 1,100 points. To try
this yourself, copy `bonus-combos.csv`, give one combo a huge value such as
100000 so the search must include it, plan with `--combos` and that copy, and
subtract it from the score again.

It also writes the route as a GPX file for Garmin BaseCamp and GPS units,
named with when it was made and the route's points, e.g.
`route-20261031-143005-11103pts.gpx` (or the name given with `--gpx`), so a
new run never overwrites an earlier one. The file has a waypoint for each
stop and a route through them in order, from Rally HQ back to Rally HQ. Each
point's comment holds its point value, and its description gives the stop
number, state and planned time.

```bash
python planRoute.py                       # reads bonus-lat-lon-points.csv
python planRoute.py --hours 8 --speed 50  # different time budget and speed
```

It only uses Python's standard library, so it also runs under
[PyPy](https://pypy.org), a faster Python, with the same results. A full
run takes about 40 seconds with PyPy versus 5 minutes with regular Python.
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
| `--first` | none | Start with these bonuses, in this order, e.g. `CGSH,SMCH` (see below) |
| `--must` | none | Visit these bonuses, in whatever order fits best (see below) |
| `--start` | 07:00 | Rally start time, for the hours bonuses are open |
| `--ignore-hours` | | Plan as if every bonus is open all day |
| `--combos` | bonus-combos.csv | Combo bonuses from the rally book, used if the file exists |
| `--ignore-combos` | | Plan without the combo bonuses |
| `--workers` | all cores | How many CPU cores to search with |
| `--gpx` | route-DATE-TIME-POINTSpts.gpx | Where to write the GPX file |

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

### Choosing the first stops, or stops the route must have

`--first` makes the route start with the bonuses you name, in the order you
give them, and the search plans the rest of the day after them. It's for
trying out other routes, such as heading straight for the big bonuses:

```bash
python planRoute.py --first CGSH,SMCH
```

Codes can be upper or lower case. It stops with an error if a code isn't in
the bonus file or if those stops alone, with the drive back to Rally HQ,
don't fit in the time budget. `planRouteExact.py` takes it too.

Compare the `Banked:` line and total with a run without `--first`. On the
2026 map, starting with CGSH and SMCH scores about 1,100 points less and
banks less at every hour, because the normal route collects bonuses along the
way and still reaches those two by hour 4.

`--must` is the same idea without fixing the order: the route has to visit
the bonuses you name, and the search decides when, around everything else.
The web app's "Must visit" box does this.

```bash
python planRoute.py --must MTNH,ENOR,UGCB
```

It stops with an error if those bonuses can't all fit in one day together.
The two can be combined, and `planRouteExact.py` takes both.

### Finding clusters of bonuses

`findClusters.py` lists where the points are most concentrated. It tries
each bonus as the center of a circle, scores it by the points inside, and
picks the best circles that don't share bonuses. For each cluster it shows
the hours to visit all of its bonuses in a loop, the points per hour of
working it, and how far it is from Rally HQ. It takes a second and ignores
bonus hours and combos.

```bash
python findClusters.py --radius 20 --speed 60 --stop-minutes 8 --road-factor 1.25
```

Try a few radii: 10 miles shows tight groups you can sweep in an hour, 35
miles shows regions worth a half day. Feed a cluster to the planner with
`--must` or `--first` to see whether it pays. On the 2026 map the densest cluster is
around Statesboro (BISH, LOGS, FABF and others), but it's about 160 road
miles from HQ: an 8-hour route forced to start there (`--first LOGS`) scores
6,171 against 8,108 without, because the round trip eats over 5 hours.

### How the search works

`planRoute.py` builds a route by adding bonuses one at a time, then keeps
trying changes to it and keeps any change that scores higher. It repeats
this from many different starting points and returns the best result. There
is no randomness, so the same inputs always give the same route.

**Scoring.** A route's time is its driving time (straight-line miles × road
factor ÷ speed, slower inside a slow zone), plus the stop at each bonus, plus
the gas stops. A route over the time budget is rejected. Its value is its
total points, including any combos it completes, plus the early-arrival
credit when `--front-load` is above 0.
When two routes are compared, the higher value wins; on a tie, the one that
collects its points sooner; then the one that takes less time.

1. **Add the best-value bonus until nothing fits** (`insert_greedily`). For
   every unvisited bonus, at every place it could go in the route, work out
   the extra time it would add, including any extra gas stop. Skip anything
   that would go over budget, add the bonus and position with the best
   *points ÷ (extra hours) ^ weight*, and repeat. A weight above 1 favors
   nearby bonuses; below 1, it will drive farther for big ones. The one
   bonus still missing from a combo also counts the combo's points. With
   front-loading on, the points also count credit for arriving early, minus
   the delay the new stop causes every stop after it.
2. **Tidy the order** (`two_opt`, `orient`). Reverse any stretch of the route
   that cuts total time, which removes places where it crosses itself. With
   front-loading on, a reversal that raises the value is also kept, as long
   as the route still fits. Then drive the loop in whichever direction
   collects points sooner, and run step 1 again in case the time saved makes
   room for another bonus.
3. **Drop stops and refill** (`local_search`). Try removing each run of 1 to
   `--max-drop` stops in a row and refilling with steps 1 and 2. Take the
   first refill that beats the current route and start over, until no
   removal helps. This gets the search out of early choices that looked good
   at the time but blocked better combinations later.
4. **Many starting points** (`solve`). Run steps 1–3 from an empty route and
   from each bonus on its own (skipping bonuses too far for a round trip), so
   every bonus gets a chance to anchor the route. Each start is tried with
   weights 0.5, 0.75, 1, 1.5 and 2, which is about 675 runs for 2026. Adding
   one bonus at a time rarely builds a whole combo, so it also starts from
   each set of combos whose bonuses fit in the day together, a route through
   all of them. The
   runs are spread across all CPU cores and their results are compared in a
   fixed order, so the winner doesn't depend on how many cores there are.
5. **Polish the winner.** Alternate a swap search (`swap_search`: replace
   each stop with each unvisited bonus, then refill) with step 3 until
   neither helps. Then reorder the stops (`front_load_order`: reverse any
   stretch or move any one stop) to collect points sooner within the budget,
   without changing which bonuses are visited. Finally, check that no bonus
   repeats and the route fits the budget.

**Limits.**

- It only keeps changes that score higher right away, so it can miss a
  better route that's only reachable through a worse one in between. For
  example, it never swaps two stops for three different ones in one move.
  `planRouteExact.py` (below) is meant to close that gap.
- Distances are straight lines at one average speed. Rivers, mountains and
  missing roads are only covered by `--road-factor`.
- Gas stops are counted for every `--gas-miles` driven in total. Where in
  the day they fall, and whether a station is nearby, isn't considered.

## Checking the route with Google Maps

`planRoute.py` and `planRouteExact.py` only estimate distances, as straight
lines. `checkRoute.py` asks the Google Maps Routes API for the real
driving route through the stops in a GPX file they wrote, keeping the same
order. With no file named, it checks the newest `route*.gpx` in the folder
(from either planner) and prints which one.

```bash
python checkRoute.py                                   # newest route, no traffic
python checkRoute.py --depart "2026-11-07 07:00"       # with traffic forecast
python checkRoute.py route-exact-20261031-143005-11103pts.gpx --hours 9.5
```

It prints, for each stop:

- the straight-line miles the plan used and Google's road miles;
- Google's driving time for the leg;
- when you'd arrive and leave, counting the picture stops and gas stops the
  same way `planRoute.py` does, and the time of day you'd arrive;
- the running score.

It uses the bonus hours in `bonus-lat-lon-points.csv` (`--bonuses` names
another file), counted from the rally start: `--start`, or the time of
`--depart` if given. Arriving before a bonus opens, it waits; arriving after
it closes, the bonus is marked `MISSED` and its points aren't counted, and
the summary lists every missed bonus. A combo counts only if every one of its
bonuses is made in time (`--combos`, default `bonus-combos.csv`); one lost to
a missed bonus is listed as `LOST` on the `Combos:` line.

Then it says whether the day `FITS`, with the minutes to spare, or is
`OVER`, and by how much. Last, it suggests a `--road-factor` (road miles ÷
straight-line miles) and `--speed` (road miles ÷ driving hours) for
`planRoute.py` that match Google's numbers. With the default Atlanta slow
zone on, the plan also slows Atlanta driving on top of that speed, so plan
with `--no-slow-zone` too if you use the suggested speed for a route that
goes through Atlanta.

It also writes `route-google-DATE-TIME-POINTSpts.gpx`: the same waypoints and
route as the file it checked, with Google's times in each description, plus a track along the
roads Google chose, for BaseCamp and GPS units.

**Traffic.** Without `--depart` the whole route goes in one request (one per
25 stops) and the times have no traffic. With `--depart`, each leg is its own
request, leaving when you'd leave that stop, so each leg gets Google's
traffic forecast for that time of day. The time is in your computer's time
zone unless you add one (`"2026-11-07 07:00-05:00"`), and it must be in the
future.

**Cost.** One request for a route of up to 25 stops, or one per leg with
`--depart` (about 20 for a full day). Google gives 5,000 free requests a
month of the kind that uses traffic or more than 10 stops, and 10,000 of the
basic kind, so checking a route is normally free; past that it's $5–10 per
1,000 requests. Check Google's
[pricing list](https://developers.google.com/maps/billing-and-pricing/pricing)
for current numbers.

| Option | Default | Meaning |
| --- | --- | --- |
| `--depart` | none | When you leave Rally HQ; turns on the traffic forecast |
| `--hours` | 9.5 | Time budget, Rally HQ to Rally HQ |
| `--stop-minutes` | 5 | Time at each bonus to take its picture |
| `--gas-miles` | 175 | Stop for gas each time the route passes another this many miles; 0 for none |
| `--gas-minutes` | 10 | Time for each gas stop |
| `--bonuses` | bonus-lat-lon-points.csv | Bonus file with the hours bonuses are open |
| `--start` | 07:00 | Rally start time, for bonus hours (the time of `--depart` if given) |
| `--combos` | bonus-combos.csv | Combo bonuses, scored when every bonus in one is made |
| `--gpx` | route-google-DATE-TIME-POINTSpts.gpx | Where to write the GPX file |

## Provably best route

`planRouteExact.py` uses the same assumptions and prints the same table and
GPX file (named `route-exact-DATE-TIME-POINTSpts.gpx` by default), but solves the problem exactly with
Google's free [OR-Tools](https://developers.google.com/optimization) CP-SAT
solver. It runs locally, with no Google API calls and no cost.

```bash
python planRouteExact.py                       # reads bonus-lat-lon-points.csv
python planRouteExact.py --hours 8 --time-limit 1800
```

While it runs, it shows the best route found so far and the most any route
could still score, updated every 5 seconds. It ends with one of:

- `PROVEN OPTIMAL`: no route scores more under these assumptions.
- `NOT PROVEN`: it hit `--time-limit` (600 seconds by default) first. It
  prints the best route found and the most any route could score, so you know
  how much might be missing. Raise `--time-limit` to keep going.

It starts from `planRoute.py`'s best route, so it never reports a worse one.
With the 2026 bonuses and default settings, it proves days up to 8 hours
in a few minutes:

| Day | Proven best | Solve time | `planRoute.py` |
| --- | --- | --- | --- |
| 4 h | 3,173 | 2 s | 3,173 |
| 6 h | 5,658 | 1 min | 5,658 |
| 7 h | 6,970 | 3 min | 6,970 |
| 8 h | 8,774 | 4½ min | 8,655 |

So `planRoute.py` usually finds the best route, but not always (119 points
short at 8 hours). A full 9.5-hour day is much harder to prove; give it a
long `--time-limit` and check how big the remaining gap is.

With the 2026 bonus hours, it proves the same points as `planRoute.py` for
4, 5 and 6 hours: 2,974, 3,661 and 5,253, in 7 s, 3 min and 8 min. The hours
make it slower, since it has to time every route.

It takes the same options as `planRoute.py`, including gas stops, slow
zones, bonus hours and combos, except `--front-load`; it only maximizes total
points.

The solver works in hundredths of a second and rounds driving times up to
be safe, so it could rule out a route that fits with less than a second to
spare. If `planRoute.py` finds such a route scoring more, it reports that
route instead, marked `NOT PROVEN`.

## Web app

`webapp/` is a small password-protected website where others can run
`planRoute.py` scenarios and see the results: a form with the planner's
settings, then a page with the route table, a map of the stops and a GPX
download. Every run is saved and listed on the home page to compare, and the
same settings on the same data show the saved result straight away. Runs go
one at a time, since each uses every CPU core; on a 4-core server one takes
about a minute. It never calls Google, so it costs nothing beyond the server.
The exact solver isn't included: it can run for hours.

It reads the files from step 1, `bonus-lat-lon-points.csv` and
`bonus-combos.csv`. The bonus data comes from the rally book, so keep the
password to people the rally allows to see it.

### Running it on a cloud server

`docker-compose.yml` runs the app under PyPy, plus [Caddy](https://caddyserver.com),
which gets an HTTPS certificate automatically so the password isn't sent in
the clear.

1. Create a Linux server (Ubuntu 24.04) with 4 vCPUs and 4–8 GB of memory,
   from any provider (Hetzner, DigitalOcean, Linode, ...). Allow incoming
   ports 22, 80 and 443. More vCPUs make each run faster.
2. A domain name for it: either point one you own at the server's IP, or use
   [sslip.io](https://sslip.io), which needs no setup: for IP 203.0.113.5,
   use `203-0-113-5.sslip.io`.
3. Install Docker on the server:

    ```bash
    ssh root@SERVER 'curl -fsSL https://get.docker.com | sh'
    ```

4. Copy the code and the bonus files from this folder (the repo has no remote
   to clone from):

    ```bash
    rsync -a --exclude .venv --exclude .git --exclude '*.gpx' ./ root@SERVER:/opt/rally-route-finder/
    ssh root@SERVER 'mkdir -p /opt/rally-route-finder/data'
    scp bonus-lat-lon-points.csv bonus-combos.csv root@SERVER:/opt/rally-route-finder/data/
    ```

5. On the server, set the password and domain, then start it:

    ```bash
    cd /opt/rally-route-finder
    printf 'APP_PASSWORD=%s\nDOMAIN=%s\n' 'choose-a-password' '203-0-113-5.sslip.io' > .env
    docker compose up -d --build
    ```

Copy the bonus files before the first `docker compose up`: if `data/` doesn't
exist then, Docker creates it empty and owned by root, and the site says "No
bonus data on the server yet". To fix that, run `docker compose down`, remove
the empty `data/`, then do step 4's copy again and start it.

Then open `https://DOMAIN`. The browser asks for a user name and password:
any user name works, with the password from `.env`.

- **New bonus data:** run step 1 again here, and copy the two CSVs into
  `data/` on the server as in step 4. No restart needed; runs with the new
  data are planned fresh, and earlier ones stay listed.
- **New code:** repeat the `rsync` in step 4, then
  `docker compose up -d --build` on the server. Saved runs are kept (in a
  Docker volume), and runs that were waiting start again.
- **Change the password:** edit `.env`, then `docker compose up -d`.
- **Logs:** `docker compose logs -f app`.

### Trying it locally

```bash
docker build -t rally-route-finder .
docker run --rm -p 8000:8000 -e APP_PASSWORD=test -v "$PWD:/data:ro" -v "$PWD/web-scenarios:/results" rally-route-finder
```

Then open <http://localhost:8000> (password `test`). Or without Docker,
under regular Python (runs take about 5 minutes):

```bash
pip install -r webapp/requirements.txt
APP_PASSWORD=test flask --app webapp/app.py run
```
