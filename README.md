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

    If your rally's files aren't laid out like SNAFU's, skip this step and
    write the planner's two files yourself; see [Input file
    formats](#input-file-formats).

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
    and GPS units show these symbols. To change the colors or where they
    switch, edit `HIGH_POINTS`, `LOW_COLOR` and `HIGH_COLOR` at the top of
    `extractDatafromGPX.py`. Everything else in the file is unchanged.

    GPX Studio doesn't show Garmin's number symbols, only its own list of
    about 40 Garmin names (Summit, Alert, Gas Station and so on), so the
    script also writes `bonus-lat-lon-points-gpxstudio.gpx`: the same file,
    with a GPX Studio icon for each bonus's points. Load that one into GPX
    Studio, and the other into BaseCamp or a GPS.

    | Points | Symbol | GPX Studio icon |
    |---|---|---|
    | 800 and up | Summit | mountain |
    | 500–799 | Alert | warning triangle |
    | 300–499 | Binoculars | binoculars |
    | under 300 | Information | ⓘ |
    | Rally HQ | House | house |

    To change them, edit `GPX_STUDIO_SYMBOLS` and `GPX_STUDIO_HQ`; the
    names GPX Studio knows are in its
    [symbols.ts](https://github.com/gpxstudio/gpx.studio/blob/main/website/src/lib/assets/symbols.ts).

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

## Input file formats

### What the planners read

Everything that plans or checks a route (`planRoute.py`,
`planRouteExact.py`, `planRouteSearch.py`, `findClusters.py`,
`checkRoute.py` and the web app) reads just two files. `extractDatafromGPX.py`
writes them from SNAFU's files, but you can make them any way you like, e.g.
from a spreadsheet saved as CSV.

**`bonus-lat-lon-points.csv`**: one line per bonus, plus one for Rally HQ.
No header row (one would be skipped with a warning).

```
ABAC, 31.4813266787678, -83.526049414649606,510, GA, ,
BISH, 32.412236854434013, -81.78479871712625,960, GA, 11:00, 13:00
Rally HQ Warner Robins, 32.618909021839499, -83.69694602675736,0, N/A, ,
```

| Column | Meaning |
| --- | --- |
| 1. code | The bonus's code, e.g. `BISH`. Unique, no commas or spaces; use capitals, since the web app capitalizes must-visit codes. |
| 2. lat | Latitude in decimal degrees, e.g. `32.4122` |
| 3. lon | Longitude in decimal degrees; negative west of Greenwich, e.g. `-81.7848` |
| 4. points | Whole number. A line whose points aren't a number (e.g. `ERROR`) is skipped with a warning. |
| 5. state | Any text, e.g. `GA` or `N/A`; shown in the route table and counted as "States". |
| 6. opens | Optional: 24-hour `HH:MM` the bonus opens, e.g. `11:00` |
| 7. closes | Optional: 24-hour `HH:MM` it closes, e.g. `13:00` |

- **Rally HQ** is the line whose code contains `Rally` (capital R), e.g.
  `Rally HQ Warner Robins`. Every route starts and ends there; its points are
  ignored. There must be exactly one; the planners stop if there's none.
- **Hours** are clock times on the rally day, counted from `--start` (7:00
  by default). Leave both blank, or leave the columns off, for a bonus open
  all day. Give both or neither, closing after opening; hours that run past
  midnight aren't supported.
- The first five columns are required on every line; spaces around values
  are ignored.

**`bonus-combos.csv`** (optional): one line per combo, no header. Its points
come on top of the bonuses' own points, once the route has every bonus in
it.

```
CMB3, 3500, BISH GSUE STRU WJMS WWRD
```

| Column | Meaning |
| --- | --- |
| 1. code | The combo's code; not one of the bonus codes |
| 2. points | Whole number |
| 3. bonuses | The bonus codes it needs, separated by spaces (not commas) |

A combo naming a bonus that isn't in `bonus-lat-lon-points.csv` is skipped
with a warning. Without the file, routes are planned with no combos.

The planners read both files from the current directory (`planRoute.py`
also takes the bonus file's name as its argument, and `--combos` names the
combo file); the web app reads them from `DATA_DIR` (`data/` in Docker).

### What the extractor expects

`extractDatafromGPX.py` builds those two files from three of the rally's
files. It's written for SNAFU's layout; if yours differ, either change it
or write the two files above directly.

**The bonus CSV** (first argument). Only column 1, the code, and column 4,
the points, are used; columns 2 and 3 (the CSV's lat/lon, in any format) are
ignored in favor of the GPX, and any later columns too. A header row is
fine: it matches no waypoint, so it's ignored. UTF-8 or Windows (Excel)
encoding.

```
CODE,LAT,LONG,POINTS,AVAIL
ABAC,N31 28.880' ,W83 31.563',510,
```

**The GPX file** (second argument). One `<wpt>` per bonus, with its
`lat`/`lon` attributes and a `<name>` that matches the CSV's code exactly
(`ABAC`, not `ABAC - Abraham Baldwin`). One waypoint has `Rally` in its name
for Rally HQ. The state comes from a Garmin `State` extension (as BaseCamp
writes it); without one it's `N/A`. Waypoints with no matching code in the
CSV are written with `ERROR` points and a warning.

**The rally book PDF** (optional third argument), for hours and combos. It
must be a PDF with real text, not a scan. The extractor looks for:

- **Hours:** each bonus's entry starts with a line beginning with its code,
  followed by a line with `Available: 24 hours` or `Available: 11:00 AM –
  1:00 PM` (12-hour times; a dash or en dash). A bonus with no `Available:`
  line gets a warning and is treated as open all day.
- **Combos:** a section headed `COMBINATION BONUSES`, where each combo is a
  line starting with its code, then `Points: 3500`, then `Successfully
  claim the bonuses: BISH, GSUE, STRU` (which may wrap onto more lines).

## Planning the route

`planRoute.py` plans a route using only the file made in step 1, so it's free.
It searches thoroughly, so
it can take a few minutes; it uses all CPU cores and shows its progress
while it runs.

It estimates distances as straight-line miles between bonuses, and time as
distance ÷ average speed, plus 3 minutes a leg for leaving the main road and
parking, a stop at each bonus to take its picture and a gas stop every 175
miles. Driving through Atlanta (inside I-285 plus about 5 miles) is slowed
to 25 MPH. The
route starts and ends at Rally HQ and fits in the time budget. It prints each
stop in order with leg miles, running hours, arrival time and running score.

**Bonus hours.** If the CSV has hours from the rally book (step 1), a route
only counts a bonus it reaches while it's open. It reaches one early only by
waiting there until it opens, and that wait comes out of the time budget; it
never reaches one after it closes, and it plans to get there at least 10
minutes before closing (`--window-margin`), so one slow leg on the day
doesn't cost the bonus. Hours are clock times, counted from the
rally start (`--start`, 7:00 by default, as in the 2026 rally book). The
table shows each bonus's hours and any wait, e.g. `waits 12 min to open at
11:00`. `--ignore-hours` plans as if every bonus were open all day, to see
what the hours cost. With the 2026 defaults, the hours cost 557 points:
10,546 instead of 11,103. `--skip-timed` instead leaves out every bonus with
hours, planning only the ones open all day, for a day with no waiting and no
closing times to make. Combos that need a left-out bonus can't be scored.

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

The route carries Garmin's trip extensions, as BaseCamp writes them, so a
Garmin GPS (e.g. a zūmo 396) imports it as a **trip**: each stop is a via
point, kept in order and announced on arrival, and the trip is routed for a
motorcycle. The GPS works out its own roads between stops, with its own
map and route settings (avoid highways and so on), so its times and miles
differ from the plan's estimates, but the order stays the plan's. To load
it:

- **USB:** connect the GPS, copy the GPX file into its `GPX` folder, and
  disconnect it. Open **Trip Planner**; the unit offers to import the file,
  and the route then appears there as a trip.
- **BaseCamp:** import the file, then send the route to the device.
- **The web app:** a scenario's **Download GPX** link gives the same file,
  as does a Google check's GPX (which adds Google's roads as a track for
  the map).

The waypoints come along too, as saved locations with their points in the
comment. Reloading a newer route adds another trip; delete old ones in
Trip Planner so you don't ride the wrong one.

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
| `--hours` | 10 | Time budget, Rally HQ to Rally HQ |
| `--deadline` | `--hours` | Hours after the start you must be back by; confidence is measured against it |
| `--late-penalty` | `15:25,30:50` | The penalty for being back late, for the expected score: up to MINUTES late, PERCENT off; later than the last is a DNF |
| `--best-budget` | off | Try budgets from the deadline down and keep the one with the highest expected score (see [Confidence](#confidence)) |
| `--speed` | 50 | Average speed in MPH |
| `--stop-minutes` | 5 | Time at each bonus to take its picture |
| `--leg-minutes` | 3 | Time every leg takes on top of driving: leaving the main road, finding the bonus, parking. None between bonuses at the same spot (see below) |
| `--road-factor` | 1.23 | Multiplies straight-line miles to approximate road miles (Google checks of 2026 routes gave 1.20-1.23) |
| `--gas-miles` | 175 | Stop for gas each time the route passes another this many miles; 0 for none |
| `--gas-minutes` | 10 | Time for each gas stop |
| `--slow-zone` | Atlanta | `LAT,LON,RADIUS_MILES,MPH[,STOP_MINUTES]`: the part of any leg inside this circle goes at MPH, and each bonus inside it takes STOP_MINUTES more. Repeat for more zones; the default is `33.78,-84.39,15,25,0` |
| `--no-slow-zone` | | Turn off the default Atlanta slow zone |
| `--athens-slow-zone` | off | Add a slow zone for downtown Athens and UGA, `33.951,-83.376,3,20,5` (see below) |
| `--savannah-slow-zone` | off | Add a slow zone for downtown Savannah, `32.081,-81.091,5,20,5` |
| `--augusta-slow-zone` | off | Add a slow zone for downtown Augusta, `33.474,-82.011,3,20,5` |
| `--max-drop` | 6 | Longest run of stops the search tries removing at once; higher is slower |
| `--front-load` | 0 | Favor collecting points early, in case the day is cut short (see below) |
| `--first` | none | Start with these bonuses, in this order, e.g. `CGSH,SMCH` (see below) |
| `--must` | none | Visit these bonuses, in whatever order fits best (see below) |
| `--only` | off | Route only the `--must` and `--first` bonuses, adding nothing else |
| `--quick` | off | Plan with the beam search instead: about 4x faster, as good on the 2026 bonuses (see [Tree search](#tree-search-beam-and-depth-first)) |
| `--start` | 07:00 | Rally start time, for the hours bonuses are open |
| `--window-margin` | 10 | Reach a bonus with hours at least this many minutes before it closes |
| `--ignore-hours` | | Plan as if every bonus is open all day |
| `--skip-timed` | | Leave out every bonus with opening hours |
| `--combos` | bonus-combos.csv | Combo bonuses from the rally book, used if the file exists |
| `--ignore-combos` | | Plan without the combo bonuses |
| `--workers` | all cores | How many CPU cores to search with |
| `--gpx` | route-DATE-TIME-POINTSpts.gpx | Where to write the GPX file |

### Leg minutes and the bonus-hours margin

Driving time alone undercounts short hops. On the 174 legs in the saved
Google checks, the 60 legs under 5 straight-line miles took Google 342
minutes, and the planner, at the speed that best matched the rest, planned
168 of them: 0.2 miles is 5 minutes on real roads, not 0. Every leg has a
fixed part (off the main road, find the bonus, park, back out), so a dense
cluster of cheap bonuses looks almost free to the planner and isn't.

`--leg-minutes` adds that fixed part to every leg (except between bonuses at
the same spot, under 0.05 miles apart). Fitted to those legs with the slow
zones on and road factor 1.23, 3 minutes a leg and 54 MPH matched best and
made the short legs right (336 minutes planned against Google's 342). With
it, the planner sees what each extra stop costs and drops low-value stops
to reach the big ones.

`--window-margin` plans to reach a bonus with hours at least that many
minutes before it closes. A route planned to reach BISH one minute before it
closed reached it 29 minutes late on Google; the margin keeps a short
slip from costing the bonus.

Numbers quoted elsewhere in this README come from before these two
settings; add `--leg-minutes 0 --window-margin 0` to plan as they did.

### Confidence

Under the route, every planner prints how likely the day is to go as
planned, and the web app shows it with each scenario: in the list, the
**Conf.** column and a **Back by** column with when half and 90% of the
simulated days are back (e.g. `17:01 to 18:45`; it sorts by the 90% time),
and on the scenario's page, a box and the full line:

```
Confidence: 46% of 2,000 simulated days make every bonus and get back by 17:00; half are back by 17:01, 90% by 18:45; VALD missed on 36%
```

It replays the route on 2,000 simulated days, drawing each leg's time and
each stop at random around the plan, and counts the days that reach every
bonus with hours before it closes and get back to HQ in time. A bonus
reached after it closes is skipped and the day goes on. It uses no Google
calls, and the same route always gives the same number. On each day:

| What varies | How much | Where it comes from |
|---|---|---|
| Each leg's time | ±30% (standard deviation) | Google's times on 24 legs of two 2026 checks, against the plan's |
| The whole day, every leg at once | ±7% | a guess: weather, traffic, the rider |
| A stop running long | 1 stop in 10, by 10 min on average | a guess: no parking, a hard-to-find sign, a wrong turn |
| A gas stop | ±30% | a guess |

Every leg and gas stop averages the plan's time, so only the long stops
add time on average, about a minute a stop. To change these, edit
`LEG_SPREAD`, `DAY_SPREAD`, `STOP_TROUBLE`, `STOP_TROUBLE_MINUTES` and
`GAS_SPREAD` at the top of `planRoute.py`.

#### Why a full route scores 35–50%

With the time budget at the deadline, the planner fills the day: the 2026 routes finish at 9.9 to 10.0 of 10
hours, with no reserve. Any delay makes such a route late, and on a real day
some legs run long, so about half the simulated days go a little over. The
14 ten-hour scenarios saved in November 2026 scored 34–49%; the three planned
for 8¾ or 9 hours against a 10-hour deadline scored 82–86%. A low number on a full
route doesn't mean the plan is bad; it means the plan has no slack, and the
**90% time** says how much slack covers most days.

#### What makes a day run long

Turning each kind of variation on alone, for the 8,487-point quick route
(10 hours, back by 17:00 as planned, with 8.3 hours of driving in 17 legs):

| Varying only | Confidence | Half back by | 90% back by |
|---|---|---|---|
| nothing | 100% | 16:59 | 16:59 |
| each leg (±30%) | 53% | 16:56 | 18:01 |
| the whole day (±7%) | 52% | 16:58 | 17:44 |
| stops running long (1 in 10, ~10 min) | 23% | 17:09 | 17:40 |
| all of them | 41% | 17:12 | 18:37 |

- **The whole day** matters most for its size. 7% doesn't sound like much,
  but it applies to all 8.3 hours of driving at once, so it moves the 90%
  time about 45 minutes. Leg-to-leg errors partly cancel over 17 legs; a
  day-wide slowdown doesn't.
- **Each leg** spreads the finish most, mostly through the few long legs:
  the three legs over an hour each make up most of it. Short hops between
  nearby bonuses hardly matter.
- **Stops running long** are the only thing that adds time on average
  (about a minute a stop), so they push even the typical day past the
  deadline; that's why confidence drops to 23% with stops alone.

#### The trade-off: points for reserve

There are two time settings. The **time budget** (`--hours`) is what the
planner fills; the **deadline** (`--deadline`) is when you must be back at
HQ, and confidence is measured against it. Plan for less than the deadline
to keep a reserve. On the command line the deadline defaults to the time
budget; on the web form it's its own field, 10 hours by default, and a
budget over the deadline is refused. Scenarios saved before the deadline
was a setting were scored again against 10 hours (or their own budget, if
longer).

With the 2026 defaults, a 10-hour deadline (17:00), in quick mode:

| Time budget | Points | Confidence | 90% of days back by |
|---|---|---|---|
| 10 hours | 8,487 | 41% | 18:37 |
| 9½ hours | 7,815 | 64% | 17:53 |
| 9 hours | 7,349 | 77% | 17:32 |
| 8¾ hours | 7,233 | 85% | 17:14 |
| 8½ hours | 6,949 | 91% | 16:51 |
| 8¼ hours | 6,525 | 93% | 16:38 |

```bash
python planRoute.py bonus-lat-lon-points.csv --hours 8.75 --deadline 10
```

To be back by 17:00 on nine days in ten, plan for about 8½ hours, which
costs about 1,500 points (18%). Whether that's worth it depends on the
rally's penalty for being late against the points; a plan in between, say
9 hours, is late on fewer days without giving up as much.

A bonus's **miss rate** says which closing time is tight: on the top
November scenario, VALD was missed on 36% of days. Raise
`--window-margin` (the web app's bonus hours margin) to reach it earlier,
or plan without it.

#### What's measured and what's a guess

- **Measured:** the ±30% per leg, from the two saved Google checks (24
  legs). Each new Google check gives more legs to measure it with.
- **Guesses:** the ±7% for the whole day, the 1-in-10 stop running about
  10 minutes long, and the gas stop spread. These matter most for the
  number, so treat it as a comparison between routes more than a forecast.
  A GPS track of a real rally day, compared leg by leg and stop by stop
  with its plan, would measure them.

#### Expected score and the best time budget

Confidence alone doesn't say which budget to ride: more points with more
risk, or fewer points made safely? The rally's late penalty settles it. The
2026 rally book:

| Back at HQ | Penalty |
|---|---|
| by 5:00 PM | none |
| 5:01–5:15 | 25% off the bonus total |
| 5:16–5:30 | 50% off |
| 5:31 or later | DNF, scored 0 |

So each simulated day also gets a score: the route's points, less any bonus
reached after it closed (and any combo that needed it), less the late
penalty. The **expected score** is the average over the 2,000 days. It's on
the confidence line, in the web app's **Exp.** column, and in a box on the
scenario's page. Set the penalty with `--late-penalty` (the web form's
**Late penalty** field) as `MINUTES:PERCENT` pairs: `15:25,30:50`, the
default, is the 2026 rule, and anything later than the last pair is a DNF.
An empty value means a DNF as soon as you're late.

`--best-budget` (the web form's **Find the best time budget** switch) finds
the budget with the highest expected score for the deadline. It plans in
quick mode for budgets from the deadline down, a quarter hour apart, until
three in a row don't beat the best, then an eighth of an hour either side of
the best. Without `--quick` it then plans the winning budget with the full
search too, and keeps whichever route expects more. The time budget setting
is ignored. It takes about a minute in quick mode on the development machine; the web app
shows the budgets it tried in a table on the scenario's page.

```bash
python planRoute.py bonus-lat-lon-points.csv --best-budget --deadline 10 --quick
```

With the 2026 defaults:

| Budget | Points planned | Confidence | Expected score |
|---|---|---|---|
| 10 h | 8,487 | 41% | 4,581 |
| 9½ h | 7,815 | 64% | 5,897 |
| 9 h | 7,349 | 77% | 6,221 |
| 8¾ h | 7,233 | 85% | 6,562 |
| **8⅝ h** | **7,092** | **90%** | **6,666** (best) |
| 8½ h | 6,949 | 91% | 6,609 |
| 8 h | 6,354 | 97% | 6,251 |
| 7¾ h | 6,070 | 98% | 6,019 |

Riding the full 10 hours plans the most points but expects the fewest:
most of its days run late, and those past 5:30 score nothing. Below 8⅝
hours each quarter hour gives up more points than it saves in penalties.
The best budget barely moves with the guessed spreads: gentler ones (day
±3.5%, 1 stop in 20 running long, legs ±20%) put it at 8¾ hours, harsher
ones (day ±10%, 1 stop in 7) at 8⅝. Either way, 8½–8¾ hours.

### Slow zones

A slow zone is a circle where the planner drives at a lower speed: the part
of any leg inside it goes at the zone's MPH. A zone can also add minutes to
each stop inside it, for parking and walking to the bonus. The Atlanta zone
is on by default on the command line (`--no-slow-zone` turns it off). The
web app picks slow zones from a Slow zones dropdown, with a Select all
option, and starts with none picked, so pick Atlanta there for the same
plan.

| Zone | Option | Circle | Speed | Extra a stop | Where the numbers come from |
|---|---|---|---|---|---|
| Atlanta | on by default | 15 mi: I-285 plus about 5 | 25 MPH | 0 | Google checks: legs near Atlanta averaged 28 straight-line MPH against 39 elsewhere |
| Athens | `--athens-slow-zone` | 3 mi: OCLG, UGCB, UGAA | 20 MPH | 5 min | Speed fitted to Google's leg times (below); parking a guess |
| Savannah | `--savannah-slow-zone` | 5 mi: SCAD, GHIS, WBHH | 20 MPH | 5 min | Guesses, like Athens's speed before it was fitted |
| Augusta | `--augusta-slow-zone` | 3 mi: AORC, AUGA, MEDC | 20 MPH | 5 min | Guesses |

Parking is the same 5 minutes in every downtown zone, on top of the usual
stop time, for finding a spot or walking to the bonus. It's a guess:
Google's times are driving only, so nothing has measured it. Atlanta's zone
adds none, since its circle is mostly suburbs and highway and is there for
the traffic.

The Atlanta zone matters even though routes get checked with Google: the check
reports real road times whatever the zone, but the zone decides which route
gets planned. On the saved Google checks, legs near Atlanta averaged about
28 straight-line miles an hour against 39 elsewhere, so without the zone the
planner would happily route through Atlanta and Google would then say it's
over time.

**Slow zones instead of avoiding a city.** There used to be avoid options
that left out Savannah's and Augusta's bonuses. Slow zones replaced them
because they charge for what makes a city costly, traffic and parking, and
let the planner decide: a small downtown bonus stops being worth the
time, while a big one can still earn it. The cost also applies to a
route that drives straight through, which leaving out bonuses never did.
The parking minutes are added to each leg into a bonus in the zone, so
they count once a stop, before the photo. A bonus within a quarter mile
(straight line) of the stop before is a short walk from where you parked,
so it doesn't pay parking again: Athens's OCLG, UGCB and UGAA, 0.06 to 0.14
miles apart, pay it once between them. Each circle stays clear of the interstates
around the city (I-95 and I-16 at Savannah, I-20 at Augusta) so traffic
going past isn't slowed, which is why ASCC, 8 miles out, isn't in
Savannah's zone. To be sure the planner stays out of a city, give its zone
a big stop time, e.g. `--slow-zone 32.081,-81.091,5,20,30`. The zones are
`ATLANTA_SLOW_ZONE` and the others at the top of `planRoute.py`. The
Google check uses Google's own leg times, with the usual stop time and the
same parking minutes at bonuses in the run's slow zones (`checkRoute.py`
takes the same slow zone options as `planRoute.py` for that), so the two
count stops alike; the check's table notes each "+ 5 min parking".

`--athens-slow-zone` (Athens in the web app's Slow zones dropdown) adds 3 miles
around downtown Athens and UGA at 20 MPH. It's off by default because the
gain is small. Fitted against Google's times on the 73 different legs in
the saved checks (scenario H settings), it cut the total error between the
plan's and Google's leg times from 329 to 308 minutes, mostly by fixing the
short in-town hops (UGAA to CHST is 4 miles but 16 minutes). The slowest
Athens legs, between JMBM and Athens, are slow because the roads wind (1.6
road miles per straight-line mile), which no circle can fix. It leans
slightly cautious: over those legs it plans 25 minutes more than Google in
total. That comes from 8 Athens legs on one Saturday morning's forecast, so
treat it as a rough correction.

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
The web app's "Must visit" box does this. Its "In this order" switch makes
them `--first` stops instead, visited in the order typed; with "Only the
must-visit bonuses" too, that's exactly the route you typed, e.g. one pasted
from a scenario's **Bonus list**.

```bash
python planRoute.py --must MTNH,ENOR,UGCB
```

It stops with an error if those bonuses can't all fit in one day together,
saying how long the quickest route through just them takes. For example, the
five EAGLE combo bonuses take 10.8 hours on their own at the default
settings, so `--hours 10` can't fit them. `--first` and `--must` can be
combined, and `planRouteExact.py` takes both.

`--only` routes just those bonuses, in the quickest order (every order is
tried for up to 8), and adds nothing else: the web app's "Only the
must-visit bonuses" switch. It shows what a set of bonuses costs on its own:

```bash
python planRoute.py --hours 11 --must BISH,GSUE,STRU,WJMS,WWRD --only
```

That's EAGLE alone: 6,090 points in 10.84 hours. Without `--only`, the same
11 hours adds LBTY and FABF beside them for 7,350; with no `--must` at all it
scores about 12,400, so EAGLE isn't worth it.

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

### The planner in plain terms

The planner works in two layers: fixed **rules** that decide whether a
route is allowed, and **rules of thumb** for finding a good allowed route.
It can't try every possible route; there are far too many.

**Rules every route follows**

- Start and finish at Rally HQ, within the time budget.
- Driving time is straight-line miles × the road factor, at the average
  speed, and 25 MPH through the Atlanta slow zone.
- Each leg costs the leg minutes (leaving the road, parking) on top of
  driving, and each bonus the stop minutes for its photo, plus a gas stop
  each time the miles pass another "gas every" distance.
- A bonus reached before it opens is waited for; one that would be reached
  after it closes, or within the bonus-hours margin of closing, can't be in
  the route.
- A combo's points count only if every bonus in it is visited.
- First stops and must-visit bonuses, if set, are always kept. With "only",
  nothing else is added.

**How the full search looks for a good route**

1. **Build greedily.** Keep adding the bonus worth the most points per extra
   hour of detour, slotted in where it costs the least time, until nothing
   more fits. The last missing bonus of a combo counts the combo's points.
2. **Try many starts.** Repeat that from every bonus on its own, leaning
   five ways from "nearby small bonuses" to "big ones farther away", and
   from routes that already hold whole combos: several hundred starts.
3. **Untangle.** Reverse any stretch of the route that cuts driving time,
   such as where it crosses itself.
4. **Drop and rebuild.** Remove every run of 1 to 6 stops in a row, refill
   the gap greedily, and keep any change that scores more.
5. **Swap.** Try replacing each stop with each bonus not in the route.
6. **Pick the winner.** Most points wins; then the route that collects them
   sooner; then the one that takes less time.
7. **Bank points early.** Reorder the same stops to collect points earlier
   where the hours allow (with front-load set, it will even give up some
   total points for that).

**How quick mode searches** (`--quick`, or the web app's switch): it builds
routes one stop at a time, keeping only the 2,000 most promising at each
step (points so far, plus 40% of an optimistic guess at what's still
reachable), and tries only the 12 most attractive next stops from each. It
finishes with the same drop-and-rebuild as step 4. It's faster because it
never reworks whole routes, but it can miss a route behind a stop that
doesn't look attractive yet. See [Tree search](#tree-search-beam-and-depth-first).

**What none of this knows about:** real roads (hence the road factor, and
the Google check), weather, rest breaks, or how long a photo really takes;
those go into the speed, road factor and stop minutes.

### How the search works

The same search in detail. `planRoute.py` builds a route by adding bonuses
one at a time, then keeps trying changes to it and keeps any change that
scores higher. It repeats this from many different starting points and
returns the best result. There is no randomness, so the same inputs always
give the same route.

**Scoring.** A route's time is its driving time (straight-line miles × road
factor ÷ speed, slower inside a slow zone), plus the stop at each bonus, plus
the gas stops, plus any wait for a bonus to open. A route over the time
budget, or reaching a bonus after it closes, is rejected. Its value is its
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
   all of them. With `--must`, every start already has the must-visit
   bonuses, each placed where it adds the least time (or, if that doesn't
   fit, in the quickest of all their orders), and no change may drop one;
   `--only` skips the search and returns just those. The runs are spread
   across all CPU cores and their results are compared in a
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

**Driving faster than Google.** Google's times are for driving at about the
usual speed, and Google doesn't take a speed or say what kind of road each
stretch is. `--highway-faster 10 --surface-faster 5` drives 10% faster on
highways and 5% faster on every other road (negative for slower). Each leg
comes back as turn-by-turn steps with their miles and no-traffic time; a
step Google drives at `--highway-mph` (55) or more counts as highway, and
its time is divided by 1.10, other steps by 1.05. Any traffic delay in a
`--depart` check is kept as Google forecasts it. With traffic, the faster
legs also move the departure time of every later leg. It's the same number
of requests.

```
python checkRoute.py --highway-faster 10 --surface-faster 5
```

**Fitting to Google's times.** When the route is over time or misses a
bonus's hours on Google's times, the check looks for stops to drop so the
rest fits and makes its hours, keeping the most points, and prints them:

```
To fit: drop MILR (458), CPTC (442), WILH (373), DRJA (255), STCH (250), EBZR (81).
About 9875 points in 9.48 hours, estimated from Google's legs
Fitted route written to route-fit-20261103-091500-9875pts.gpx; check it with: ...
```

Dropping early, cheaper stops can win back a big bonus later: that route
missed BISH (960) and PROP (820) by arriving late, and dropping six small
stops makes both. It's a beam search: drop one more stop at a time, keeping
the 60 best partial routes. It costs nothing, because it uses the legs Google
already gave: a leg Google drove is kept as is, and a leg that now skips a
dropped stop is the planner's estimate for it, scaled by how Google compared
with the planner over the legs it replaces. Those are estimates, so check
the fitted route (`route-fit-…gpx`, the default route to check next) with
Google before riding it.

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
| `--hours` | 10 | Time budget, Rally HQ to Rally HQ |
| `--stop-minutes` | 5 | Time at each bonus to take its picture |
| `--gas-miles` | 175 | Stop for gas each time the route passes another this many miles; 0 for none |
| `--gas-minutes` | 10 | Time for each gas stop |
| `--bonuses` | bonus-lat-lon-points.csv | Bonus file with the hours bonuses are open |
| `--start` | 07:00 | Rally start time, for bonus hours (the time of `--depart` if given) |
| `--combos` | bonus-combos.csv | Combo bonuses, scored when every bonus in one is made |
| `--gpx` | route-google-DATE-TIME-POINTSpts.gpx | Where to write the GPX file |
| `--highway-faster` | 0 | Percent faster than Google on highways; negative for slower (-50 to 100) |
| `--athens-slow-zone`, `--savannah-slow-zone`, `--augusta-slow-zone`, `--slow-zone` | | The plan's slow zones, as `planRoute.py` takes them, for their parking minutes at each stop |
| `--surface-faster` | 0 | The same for every other road |
| `--highway-mph` | 55 | A step Google drives at this speed or more counts as highway |
| `--leg-minutes` | 3 | The planner's minutes per leg, for the `--speed` it suggests and for estimating legs in a fitted route |

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
The tables below were measured under the settings before leg minutes, the
bonus-hours margin and the current defaults (see [Can the absolute best
route be found?](#can-the-absolute-best-route-be-found) for today's
numbers). With the 2026 bonuses and those older settings, it proved days up
to 8 hours in a few minutes:

| Day | Proven best | Solve time | `planRoute.py` |
| --- | --- | --- | --- |
| 4 h | 3,173 | 2 s | 3,173 |
| 6 h | 5,658 | 1 min | 5,658 |
| 7 h | 6,970 | 3 min | 6,970 |
| 8 h | 8,774 | 4½ min | 8,655 |

So `planRoute.py` usually finds the best route, but not always (119 points
short at 8 hours). A full day is much harder to prove; give it a long
`--time-limit` and check how big the remaining gap is.

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

### Can the absolute best route be found?

Under the planner's assumptions, in principle; for a full day with these
tools, no. On real roads, no.

**Under the planner's assumptions.** With the current defaults (10 hours,
50 MPH, road factor 1.23, 3 leg minutes, 10-minute hours margin),
`planRoute.py` found 8,487 points in 3½ minutes. `planRouteExact.py`,
starting from that route with 8 cores and `--time-limit 600`, found nothing
better and could only show that no route scores more than 11,529: a 26%
gap. Its bound fell quickly at first (18,738 after 1 minute, 12,521 after 4)
and then slowly (11,529 at 10), so more time won't close it. Nothing else
tried did better, measured with 10 minutes each:

| Tried | Most any route could score | Gap |
| --- | --- | --- |
| CP-SAT, defaults | 11,529 | 26% |
| CP-SAT, `linearization_level=2` | 11,519 | 26% |
| CP-SAT, bonus hours ignored (a looser problem) | 11,978 | 28% |
| SCIP mixed-integer model, stop times by big-M | 25,343 | 66% |
| Linear relaxation with subtour cuts, no hours | about 17,600 | 52% |
| Points-per-hour knapsack bound | 35,722 | |

Shorter days aren't proven quickly any more either: under the current
settings, 7 hours was left with a 10% gap after 5 minutes, and 8 hours 25%.

The gap is the bound's fault, not missing points: the 2026 bonuses are
dense (55 pairs within 10 minutes of each other, where a typical leg on the
route takes about 30), and that lets the solver's relaxation "half visit"
bonuses all over the state on half the driving. Bonus hours, gas stops and
pruning unreachable bonuses (all 134 are reachable) aren't the cause.
Proving a full day would take a different kind of solver, column generation
with branch-and-price and orienteering-specific cuts: research-level work,
with no promise it works on this data.

It isn't worth it. Where days were proven (4-8 hours, under the older
settings), `planRoute.py` matched the best or came within 1.4%, and on the
full day the heuristic, the beam search and 10 minutes of CP-SAT all stop
at 8,487. The planner's times differ from Google's by tens of minutes a
day, worth one or two bonuses (500-1,000+ points), more than the heuristic
is likely to leave behind.

**On real roads.** A provable best on Google's times needs Google's time
for every pair of places: about 18,000 legs for 134 bonuses and Rally HQ,
roughly $40-180 with the Routes API's route matrix at 2025 list prices
(estimated, not quoted). Even then it's best for one set of fixed times;
traffic and real stop times vary on the day.

**What to do instead:** plan a few strong, different routes (`planRoute.py`,
`--quick`, `planRouteExact.py` from them), check the best few with Google,
use the fit to drop stops where they're over, and refit `--speed` and
`--road-factor` from the checks.

## Tree search (beam and depth-first)

`planRouteSearch.py` is a third way to plan the same route, the
old-school AI way: a search tree. A route is built one stop at a time from
Rally HQ. Each partial route is a node, and its children are the same route
with one more bonus that still leaves time to get back. It takes the same
options as `planRoute.py` (bonus hours, gas stops, slow zones, combos,
`--first`, `--must`) except `--front-load`, prints the same table, and
writes `route-search-DATE-TIME-POINTSpts.gpx`. Like `planRoute.py`, it's much
faster under PyPy.

```bash
python planRouteSearch.py                          # beam search, about 5 seconds
python planRouteSearch.py --widen --time-limit 120 # wider and wider beams for 2 minutes
python planRouteSearch.py --method dfs --branch 0 --hours 6   # prove the best 6-hour route
```

Each node is scored f = g + h-weight × h. g is the points so far, including
any combos completed. h is the most points the rest of the day could still
add: the bonuses still reachable, packed best points per hour first into
the time left, as if each cost only its stop plus the quickest drive into it
(a "fractional knapsack"). A combo's points are shared among the stops it
still needs. h ignores gas stops and waits, so it is never too low.

Two methods:

- **Beam search** (`--method beam`, the default). Grow every route in the
  frontier by one stop, then keep only the `--beam-width` best by f (2,000),
  at most `--diversity` of them ending at the same bonus (a tenth of the
  width), so the beam doesn't fill up with variations on one route. Of routes
  with the same stops ending at the same bonus, only the quickest is kept.
  `--widen` reruns at double the width until `--time-limit`. The growing is
  spread over all CPU cores, and the result doesn't depend on how many.
- **Depth-first branch and bound** (`--method dfs`). Follow the most
  promising next stop first, all the way to the end of the day, then back up
  and try the next. Any branch whose f can't beat the best route found so far
  is cut off. It starts from a beam search's best route so it can cut from
  the start (`--beam-width 0` starts from nothing), and stops at
  `--time-limit` (60 seconds).

The cut-offs:

- `--branch` (12): only the 12 best next stops from each node are tried, by
  points per hour of getting there. Lower is faster and greedier; 0 tries
  them all.
- `--h-weight` (0.4 for beam, 1 for dfs): how much h counts. In a beam,
  lower ranks routes more by points already collected, which did better
  here. In depth-first, 1 is safe; below 1 cuts off more, finishing sooner
  but possibly missing the best route.

With `--method dfs --branch 0` and h-weight 1, nothing is cut off that could
do better, so if it finishes before the time limit, no route scores more. It
prints `no route scores more` when that happens. With the settings before
leg minutes and the hours margin, it proved the same bests as
`planRouteExact.py`, often faster:

| Day | Proven best | `planRouteSearch.py` | `planRouteExact.py` |
| --- | --- | --- | --- |
| 4 h, bonus hours | 2,974 | 1 s | 7 s |
| 5 h, bonus hours | 3,661 | 6 s | 3 min |
| 6 h, bonus hours | 5,253 | 34 s | 8 min |
| 6 h, `--ignore-hours` | 5,658 | 1 min | 1 min |

From 7 hours on it didn't finish in 15 minutes. It also uses about 2 GB of
memory by then (1 GB at 6 hours), for the table of routes it has already
seen.

How it compares with `planRoute.py` (8,667 points in about 40 seconds for
scenario H, `--road-factor 1.22 --speed 46 --stop-minutes 4`; 8,108 for the
web test, `--hours 8 --speed 60 --stop-minutes 8 --road-factor 1.25 --start
08:00 --gas-miles 200 --no-slow-zone`), on 8 cores under PyPy:

| Settings | H | Time | Web test | Time |
| --- | --- | --- | --- | --- |
| beam, width 100, branch 5 | 8,478 | 1 s | 7,967 | 1 s |
| beam, width 1,000, branch 10 | 8,592 | 4 s | 8,108 | 3 s |
| beam, width 1,000, branch 10, no diversity limit | 8,531 | 4 s | 8,108 | 3 s |
| beam, width 1,000, branch 10, h-weight 1 | 8,432 | 4 s | 7,835 | 4 s |
| beam, defaults (width 2,000, branch 12) | **8,667** | 5 s | **8,108** | 5 s |
| beam, defaults, 1 core | 8,667 | 9 s | 8,108 | 8 s |
| beam, width 5,000 | 8,667 | 10 s | 8,108 | 8 s |
| beam, `--widen` from 1,000, 60 s | 8,667 | 41 s | 8,108 | 38 s |
| dfs from the default beam, 60 s | 8,667 | 66 s | 8,108 | 65 s |
| dfs from nothing, branch 8 (finished) | 8,592 | 52 s | 8,108 | 41 s |

So the default beam search matches `planRoute.py` on both, in about an
eighth of the time, but doesn't beat it: neither did `planRouteExact.py` in
30 minutes on H. Searching longer (wider beams, depth-first from the beam's
route) found nothing better. `--polish` runs `planRoute.py`'s
drop-and-reinsert search on the result; it lifts narrow beams a little
(8,478 to 8,502 on H, 7,967 to 8,089 on the web test) but found nothing to
add to the default's routes.

**Limits.** The `--branch` cut-off ranks next stops by points per hour, which
can't see a cluster behind a small stop: on H, the 8,667 route's fifth stop
is only the 11th best by that measure, so branch 10 can never find it.
Ranking by f, or looking one more stop ahead, did no better. Tuned on the
2026 bonuses only; other maps may want other settings.

**Quick mode.** `planRoute.py --quick`, and the web app's Quick mode switch,
plan with the default beam search followed by `planRoute.py`'s
drop-and-reinsert search, in place of the full search. Timed one after the
other on this 8-core machine, including start-up:

| | Full search | `--quick` |
|---|---|---|
| H | 8,667 in 30 s | 8,667 in 8 s |
| Web test | 8,108 in 21 s | 8,108 in 5 s |

It's a fast first look; for the route you'll ride, run the full search too,
since on other data the beam may miss what the full search finds. It doesn't
do `--front-load`.

## Web app

`webapp/` is a small password-protected website where others can run
`planRoute.py` scenarios and see the results: a form with the planner's
settings, then a page with the route table, a map of the stops and a GPX
download. Every run is saved and listed on the home page to compare, and the
same settings on the same data show the saved result straight away. Runs go
one at a time, since each uses every CPU core; on a 4-core server one takes
about a minute. Planning never calls Google, so it costs nothing beyond the
server; checking a route with Google is an optional extra, off unless you
turn it on (see below). The exact solver isn't included: it can run for hours.

It reads the files from step 1, `bonus-lat-lon-points.csv` and
`bonus-combos.csv`. The bonus data comes from the rally book, so keep the
password to people the rally allows to see it.

### Running it on a server

`docker-compose.yml` runs the app under PyPy on port 80 of the server, and
optionally a guest copy on port 8000 (see below). Neither does HTTPS, so
put a tunnel in front: a [Cloudflare
Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
gives each a public HTTPS address with no ports opened on the router, and
Tailscale works for your own machines. Without one, the password crosses
the network in the clear.

1. A Linux machine with Docker (`curl -fsSL https://get.docker.com | sh`),
   e.g. a desktop at home or a cloud server with 4 or more vCPUs and 4–8 GB
   of memory. More vCPUs make each run faster.
2. Get the code and copy in the bonus files from this folder:

    ```bash
    git clone https://github.com/scrogatl/rally-route-finder.git
    mkdir -p rally-route-finder/data
    scp bonus-lat-lon-points.csv bonus-combos.csv SERVER:rally-route-finder/data/
    ```

3. On the server, set the password, then start it:

    ```bash
    cd rally-route-finder
    printf 'APP_PASSWORD=%s\n' 'choose-a-password' > .env
    docker compose up -d --build
    ```

4. Point the tunnel at it: for a Cloudflare Tunnel, add a public hostname
   with the service `http://localhost:80` (and one with
   `http://localhost:8000` for the guest site). If `cloudflared` runs in its
   own Docker container, use `http://host.docker.internal:80` instead.

Docker publishes the ports on every network the server is on, past its
firewall, so on a cloud server with a public IP block ports 80 and 8000 at
the provider's firewall, or change `"80:8000"` to `"127.0.0.1:80:8000"` in
`docker-compose.yml` to serve only the tunnel.

Copy the bonus files before the first `docker compose up`: if `data/` doesn't
exist then, Docker creates it empty and owned by root, and the site says "No
bonus data on the server yet". To fix that, run `docker compose down`, remove
the empty `data/`, then do step 2's copy again and start it.

Then open the tunnel's address and log in with the password from `.env`. A
login lasts 30 days in that browser; **Log out**, at the top right, ends it.

- **New bonus data:** run step 1 again here, and copy the two CSVs into
  `data/` on the server as in step 2. No restart needed; runs with the new
  data are planned fresh, and earlier ones stay listed.
- **New code:** `git pull`, then `docker compose up -d --build` on the
  server. If pages still look old, rebuild from scratch with
  `docker compose build --no-cache && docker compose up -d`. Saved runs are kept (in a
  Docker volume), and runs that were waiting start again.
- **Change the password:** edit `.env`, then `docker compose up -d`. That
  logs everyone out.
- **Logs:** `docker compose logs -f app`.
- **Stop or delete a run:** a waiting or running scenario's page has a
  **Stop this run** button; a running one stops within a second or so. Any
  other scenario's page has a **Delete this scenario** link, which removes it
  and its files (its GPX and any Google checks). A stopped scenario can be
  run again by submitting the same settings.
- **Bonus list:** a finished scenario's **Bonus list** button opens a box
  with the route's bonus codes in order, comma separated (start and finish
  left out), and a **Copy** button to put them on the clipboard.
- **Favorites and sorting:** click the star beside a scenario, in the list
  or on its page, to mark it a favorite; click again to unmark it. Favorites
  are saved with the scenario, so everyone using the site sees them. Sort the
  list by the star column to bring favorites to the top. The list keeps the
  last sort you chose, in that browser, between visits.
- **Archive and restore:** **Archive all**, above the list, moves every
  finished, stopped or failed scenario into an archive, out of the list, for
  a fresh start, e.g. after a change to the planner. Waiting and running
  scenarios stay. The **Archives** page lists each archive by when it was
  made, with how many scenarios and the best points, and **Restore** puts
  its scenarios back with their names, stars and Google checks. Since the
  same settings on the same data always make the same scenario, one planned
  again after archiving is already in the list; restoring keeps the list's
  copy and leaves the archived one where it is. Archives are folders in
  `archives/` in the results folder, so a backup of the volume has them.
- **A guest site to share:** the `guest` service in `docker-compose.yml`
  is a second copy of the app with its own password and its own saved
  runs, so other people's scenarios never land in your list (and yours
  aren't in theirs). It has no Google checks, so nobody else can spend
  your key, and plans with at most 4 cores, leaving the rest for your runs;
  it reads the same `data/` bonus files. Turn it on by adding to `.env`:

      COMPOSE_PROFILES=guest
      GUEST_PASSWORD=the-guest-site-password

  then `docker compose up -d --build`. It's on port 8000, for a tunnel to
  publish, e.g. a Cloudflare Tunnel public hostname pointing at
  `http://localhost:8000`. A new build updates both sites. Its logs are
  `docker compose logs -f guest`.

### Checking routes with Google

On a private site you can turn on a **Check with Google** button for
finished routes. It does what `checkRoute.py` does: Google's road miles and
driving times for each leg, when you'd reach each stop, bonuses missed for
their hours, whether the day fits, and the `--road-factor` and `--speed`
that match. The result is saved with the scenario, drawn on the map as
Google's roads, and has its own GPX download. Leave the departure blank for
one request without traffic; give a departure (Georgia time) for Google's
traffic forecast, one request per leg. **Highways % faster** and **Other
roads % faster** work like `--highway-faster` and `--surface-faster`; each
mix of departure and percents is its own saved check. The same check again
shows the saved result without asking Google. A check over time or missing
a bonus's hours also shows the stops to drop to fit (see *Fitting to
Google's times* above), with a **Make it a scenario** button: that saves the
kept stops, in the same order, as a new scenario, ready to check with
Google itself.

Every check is billed to your Google account, so **leave this off on a
site the public can reach**. To turn it on, add to `.env` on the server, then
`docker compose up -d`:

```
GOOGLE_CHECK=on
GMAPS_API_KEY=your-google-maps-key
```

The app won't start with `GOOGLE_CHECK=on` and no key. Remove the two lines
(or set `GOOGLE_CHECK=off`) and run `docker compose up -d` to turn it off
again; checks already made stay visible. Departure times are Georgia time
(`America/New_York`); set `RALLY_TZ` to change that.

### Monitoring with New Relic

The app can report to [New Relic](https://newrelic.com): **APM** for the
web requests, each planner run (a background task named `plan`, with the
run's ID, hours, quick mode and must-visit bonuses as attributes) and the
calls to Google, and **Browser** for page loads in visitors' browsers. It's
off unless a license key is set. Add to `.env` on the server, then
`docker compose up -d`:

```
NEW_RELIC_LICENSE_KEY=your-ingest-license-key
NEW_RELIC_APP_NAME=Rally Route Finder
```

The name is optional (that's the default). For Browser, also turn on
browser monitoring for this APM app in New Relic (add a Browser app that
uses the APM agent, and pick this app). New Relic then hands the agent its
browser script, and every page includes it. Any other
setting can be given as a `NEW_RELIC_*` environment variable in
`docker-compose.yml`. Remove the key to turn it off.

While New Relic is on, the app also sends a heartbeat every minute (the
metrics `Custom/Heartbeat/QueuedRuns` and `Custom/Heartbeat/Running`), so it
keeps reporting when nobody's using the site.

**Uptime checks.** `/health` on the site's address answers without the password:
`{"status": "ok"}`, or status 503 and `{"status": "planner stopped"}` if the
thread that runs the planner has died (restart with `docker compose restart
app`). Point New Relic Synthetics, or any ping monitor, at it rather than at
the home page, which needs the password. It says nothing else about the
site, and New Relic leaves its requests out of the app's statistics.

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
