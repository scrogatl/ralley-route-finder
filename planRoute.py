#!/usr/bin/env python
"""
Plan a high-scoring rally route from bonus-lat-lon-points.csv without
calling the Google API.

Distances are straight-line (great circle) miles between bonuses, so they
are rough: real roads are longer. Use --road-factor to pad them (1.3 is a
common rule of thumb). The route starts and ends at Rally HQ and must fit
in the time budget, including 5 minutes (--stop-minutes) at each bonus to
take its picture, a 10-minute gas stop every 175 miles (--gas-miles,
--gas-minutes), and slower driving through Atlanta (--slow-zone). If the
CSV has the hours bonuses are open (from the rally book, see
extractDatafromGPX.py), a bonus only counts while it's open, waiting there
if you arrive early (--start sets the rally start, --ignore-hours skips it).
Combo bonuses (bonus-combos.csv, also from the rally book) add their points
when the route has every bonus in the combo (--ignore-combos skips them).

Picking the best set of stops is the "orienteering problem", which has no
fast exact solution, so this uses a heuristic: build a route by greedily
inserting the best points-per-hour bonus, then systematically try dropping
each run of stops, re-insert, and keep the result whenever it scores higher.
That is repeated starting from every bonus with several weightings, and the
best route is polished by trying to swap each stop for an unvisited bonus.
There is no randomness, so the same inputs always give the same route. It is
thorough rather than fast: expect several minutes.

    python planRoute.py bonus-lat-lon-points.csv --hours 10 --speed 45
"""
import argparse, collections, csv, itertools, math, multiprocessing, os, signal, sys, time
import xml.etree.ElementTree as ET
from datetime import datetime

EARTH_RADIUS_MILES = 3958.8
GPX_NS = "http://www.topografix.com/GPX/1/1"

# Atlanta traffic: centered in the I-285 loop, radius covers I-285 (about
# 10 miles out) plus about 5 more; speed is a guess, change it with --slow-zone
ATLANTA_SLOW_ZONE = dict(lat=33.78, lon=-84.39, radius=15, mph=25)
# Downtown Athens and UGA (--athens-slow-zone), fitted to Google's times on
# 2026 legs: its short in-town hops took about twice the open-road time
ATHENS_SLOW_ZONE = dict(lat=33.951, lon=-83.376, radius=3, mph=20)

# Each starting route trades points against extra time differently; the
# search improves every one and keeps the best
START_WEIGHTS = (0.5, 0.75, 1.0, 1.5, 2.0)

# The rally book's start time; bonus hours are counted from it
RALLY_START = '07:00'


def load_bonuses(csv_file_path):
    """Return (hq, bonuses); each is a dict with code, lat, lon, points, state,
    and opens/closes ('HH:MM', or None if open 24 hours) when the file has the
    hours from the rally book."""
    hq = None
    bonuses = []
    with open(csv_file_path) as f:
        for row in csv.reader(f):
            if not row:
                continue
            code, lat, lon, points, state = [field.strip() for field in row[:5]]
            if 'Rally' in code:
                hq = dict(code=code, lat=float(lat), lon=float(lon), points=0, state=state)
                continue
            try:
                points = int(points)
            except ValueError:
                print(f"WARNING: skipping '{code}', points is '{points}'", file=sys.stderr)
                continue
            opens, closes = ([field.strip() or None for field in row[5:7]] + [None, None])[:2]
            bonuses.append(dict(code=code, lat=float(lat), lon=float(lon), points=points, state=state,
                                opens=opens, closes=closes))
    if hq is None:
        sys.exit(f"ERROR: no 'Rally HQ' row found in {csv_file_path}")
    return hq, bonuses


def haversine_miles(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a['lat'], a['lon'], b['lat'], b['lon']))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def parse_slow_zone(text):
    """'LAT,LON,RADIUS_MILES,MPH' -> dict, for argparse."""
    try:
        lat, lon, radius, mph = (float(v) for v in text.split(','))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected LAT,LON,RADIUS_MILES,MPH, got '{text}'")
    return dict(lat=lat, lon=lon, radius=radius, mph=mph)


def add_slow_zone_args(parser):
    parser.add_argument('--slow-zone', type=parse_slow_zone, action='append', metavar='LAT,LON,RADIUS_MILES,MPH',
                        help='the part of any leg inside this circle is driven at MPH; repeat for more zones '
                             '(default: Atlanta, I-285 plus about 5 miles: '
                             f"{','.join(f'{v:g}' for v in ATLANTA_SLOW_ZONE.values())})")
    parser.add_argument('--no-slow-zone', action='store_true', help='turn off the default Atlanta slow zone')
    parser.add_argument('--athens-slow-zone', action='store_true',
                        help='add a slow zone for downtown Athens: '
                             f"{','.join(f'{v:g}' for v in ATHENS_SLOW_ZONE.values())}")


def add_gas_args(parser):
    parser.add_argument('--gas-miles', type=float, default=175,
                        help='stop for gas every this many miles; 0 for no gas stops (default 175)')
    parser.add_argument('--gas-minutes', type=float, default=10, help='time for each gas stop (default 10)')


def describe_gas(args):
    if not args.gas_miles:
        return "no gas stops"
    return f"{args.gas_minutes:g} min gas stop every {args.gas_miles:g} mi"


def slow_zones_from_args(args):
    zones = [] if args.no_slow_zone else args.slow_zone or [ATLANTA_SLOW_ZONE]
    return zones + ([ATHENS_SLOW_ZONE] if args.athens_slow_zone else [])


def add_first_args(parser):
    parser.add_argument('--first', metavar='CODES',
                        help='start the route with these bonuses, in this order, e.g. CGSH,SMCH; '
                             'the search plans the rest of the day after them')
    parser.add_argument('--must', metavar='CODES',
                        help='visit these bonuses, in whatever order fits best, e.g. CGSH,SMCH')
    parser.add_argument('--only', action='store_true',
                        help='route only the --first and --must bonuses, in the quickest order, adding nothing else')


def bonus_indexes(planner, option, text):
    """Place indexes for a comma-separated list of bonus codes."""
    index = {place['code'].upper(): i for i, place in enumerate(planner.places) if i}
    codes = [code.strip().upper() for code in text.split(',') if code.strip()]
    unknown = [code for code in codes if code not in index]
    if unknown:
        sys.exit(f"ERROR: {option}: no bonus with code {', '.join(unknown)}")
    if len(set(codes)) != len(codes):
        sys.exit(f"ERROR: {option} names a bonus more than once")
    return [index[code] for code in codes]


def apply_first(planner, args):
    """Lock in the --first stops at the start of the planner's route, and
    the --must bonuses anywhere in it."""
    if getattr(args, 'must', None):
        planner.required = frozenset(bonus_indexes(planner, '--must', args.must))
    if getattr(args, 'only', False):
        if not (args.first or getattr(args, 'must', None)):
            sys.exit("ERROR: --only needs bonuses to route, from --must or --first")
        planner.only = True
    if not args.first:
        return
    planner.lead = bonus_indexes(planner, '--first', args.first)
    if planner.route_hours(planner.lead) > planner.max_hours:
        codes = [planner.places[b]['code'] for b in planner.lead]
        sys.exit(f"ERROR: --first {', '.join(codes)} takes {planner.route_hours(planner.lead):.2f} hours "
                 f"with the drive back, more than the {planner.max_hours} hour budget")


def load_combos(csv_file_path):
    """[(code, points, [member codes])] from bonus-combos.csv, written by
    extractDatafromGPX.py; empty if there's no such file."""
    if not os.path.exists(csv_file_path):
        return []
    combos = []
    with open(csv_file_path) as f:
        for row in csv.reader(f):
            if row:
                combos.append((row[0].strip(), int(row[1]), row[2].split()))
    return combos


def add_combo_args(parser):
    parser.add_argument('--combos', default='bonus-combos.csv',
                        help='combo bonuses from the rally book: points for getting every bonus in a group '
                             '(default bonus-combos.csv, if it exists)')
    parser.add_argument('--ignore-combos', action='store_true', help='plan without the combo bonuses')


def apply_combos(planner, args):
    """Give the planner the combos it can score."""
    if args.ignore_combos:
        return
    index = {place['code']: i for i, place in enumerate(planner.places) if i}
    for code, points, members in load_combos(args.combos):
        unknown = [m for m in members if m not in index]
        if unknown:
            print(f"WARNING: combo {code} needs {', '.join(unknown)}, not in the bonus file; it can't be scored",
                  file=sys.stderr)
            continue
        planner.combos.append((code, points, frozenset(index[m] for m in members)))


def describe_combos(planner):
    if not planner.combos:
        return "no combos"
    return "combos: " + ", ".join(f"{code} {points} ({' '.join(planner.places[m]['code'] for m in sorted(members))})"
                                  for code, points, members in planner.combos)


def clock_hours(text):
    """'15:30' as 15.5."""
    hour, minute = map(int, text.split(':'))
    return hour + minute / 60


def start_time(text):
    """argparse type for --start: a 24-hour HH:MM time."""
    try:
        hour, minute = map(int, text.split(':'))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return f"{hour:02}:{minute:02}"
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f"'{text}' isn't a 24-hour HH:MM time, e.g. 07:00")


def add_hours_args(parser):
    parser.add_argument('--start', default=RALLY_START, type=start_time,
                        help=f'rally start time, HH:MM, for the hours bonuses are open (default {RALLY_START})')
    parser.add_argument('--ignore-hours', action='store_true',
                        help="plan as if every bonus is open all day, ignoring the rally book's hours")


def describe_hours(planner):
    timed = [p for p in planner.places if p.get('opens')]
    if not planner.windows:
        return f"start {planner.start}, " + ("bonus hours ignored" if timed else "no bonus hours in file")
    return f"start {planner.start}, " + ", ".join(f"{p['code']} open {p['opens']}-{p['closes']}" for p in timed)


def describe_first(planner):
    parts = []
    if planner.lead:
        parts.append("first: " + ", ".join(planner.places[b]['code'] for b in planner.lead))
    if planner.required:
        parts.append("must visit: " + ", ".join(sorted(planner.places[b]['code'] for b in planner.required)))
    return "; ".join(parts) or "no forced stops"


def describe_slow_zones(zones):
    if not zones:
        return "no slow zones"
    return ", ".join(f"{z['radius']:g} mi slow zone at {z['mph']:g} MPH around {z['lat']:g},{z['lon']:g}"
                     for z in zones)


def fraction_inside(a, b, zone):
    """Fraction of the straight line from a to b that lies inside the zone's
    circle. Uses a flat map around the zone's center, which is accurate
    enough at metro-area sizes."""
    miles_per_lon = 69.17 * math.cos(math.radians(zone['lat']))
    ax, ay = (a['lon'] - zone['lon']) * miles_per_lon, (a['lat'] - zone['lat']) * 69.0
    bx, by = (b['lon'] - zone['lon']) * miles_per_lon, (b['lat'] - zone['lat']) * 69.0
    dx, dy = bx - ax, by - ay
    # Points along the line are a + t(b - a) for t from 0 to 1; solve for
    # where that crosses the circle, and keep the part between 0 and 1
    qa, qb, qc = dx * dx + dy * dy, 2 * (ax * dx + ay * dy), ax * ax + ay * ay - zone['radius'] ** 2
    if qa == 0:
        return 1.0 if qc <= 0 else 0.0
    disc = qb * qb - 4 * qa * qc
    if disc <= 0:
        return 0.0
    t1, t2 = (-qb - math.sqrt(disc)) / (2 * qa), (-qb + math.sqrt(disc)) / (2 * qa)
    return max(0.0, min(1.0, t2) - max(0.0, t1))


class Planner:
    """Stops are indexes into self.places; index 0 is Rally HQ."""

    def __init__(self, hq, bonuses, hours, speed, stop_minutes, road_factor, front_load, slow_zones=(),
                 gas_miles=0, gas_minutes=0, start=RALLY_START, use_hours=True):
        self.places = [hq] + bonuses
        self.start = start
        self.max_hours = hours
        self.stop_hours = stop_minutes / 60
        self.front_load = front_load
        self.gas_miles = gas_miles
        self.gas_hours = gas_minutes / 60
        n = len(self.places)
        # Estimated road miles, and travel time in hours, between every pair of places
        self.miles = [[haversine_miles(self.places[i], self.places[j]) * road_factor
                       for j in range(n)] for i in range(n)]
        self.hours = [[self.leg_hours(self.places[i], self.places[j], self.miles[i][j], speed, slow_zones)
                       for j in range(n)] for i in range(n)]
        # Cached for insert_greedily's inner loop: hours_to[j][i] is hours[i][j]
        self.hours_to = [list(column) for column in zip(*self.hours)]
        self.miles_to = [list(column) for column in zip(*self.miles)]
        self.points = [place['points'] for place in self.places]
        # Stops locked in at the start of every route (--first); the
        # search only changes what comes after them
        self.lead = []
        # Stops every route must have, in any order (--must)
        self.required = frozenset()
        # Route only the --first and --must stops, adding nothing (--only)
        self.only = False
        # Combo bonuses, (code, points, frozenset of stops): the points count
        # only if the route has every one of those stops (--combos)
        self.combos = []
        # When each bonus opens and closes, in hours after the start, or None
        # if it's open all day. self.windows is None when no bonus has hours,
        # so routes are timed the quicker way.
        windows = [None] * n
        if use_hours:
            for i, place in enumerate(self.places):
                if place.get('opens'):
                    windows[i] = (clock_hours(place['opens']) - clock_hours(start),
                                  clock_hours(place['closes']) - clock_hours(start))
        self.windows = windows if any(windows) else None

    @staticmethod
    def leg_hours(a, b, miles, speed, slow_zones):
        # The share of the leg inside each slow zone goes at that zone's speed
        # (zones shouldn't overlap, or the overlap is counted twice)
        per_mile = 1 / speed
        for zone in slow_zones:
            per_mile += fraction_inside(a, b, zone) * (1 / zone['mph'] - 1 / speed)
        return miles * per_mile

    def gas_stops(self, miles):
        """Gas stops needed to drive this many miles: one each time the
        odometer passes another gas_miles."""
        return int(miles // self.gas_miles) if self.gas_miles else 0

    def route_miles(self, route):
        miles = self.miles
        total = 0
        previous = 0
        for b in route:
            total += miles[previous][b]
            previous = b
        return total + miles[previous][0]

    def route_hours(self, route):
        if self.windows is not None:
            return self.timed_hours(route)
        # Called millions of times, so one loop over local names
        hours, miles = self.hours, self.miles
        drive = distance = 0
        previous = 0
        for b in route:
            drive += hours[previous][b]
            distance += miles[previous][b]
            previous = b
        drive += hours[previous][0]
        distance += miles[previous][0]
        return drive + len(route) * self.stop_hours + self.gas_stops(distance) * self.gas_hours

    def timed_hours(self, route):
        """route_hours when some bonuses have hours: wait at a bonus reached
        before it opens, and infinity if one is reached after it closes.
        Gas stops are made on the leg where the odometer passes each one."""
        hours, miles, windows = self.hours, self.miles, self.windows
        gas_miles, gas_hours, stop_hours = self.gas_miles, self.gas_hours, self.stop_hours
        elapsed = distance = 0
        previous = 0
        for b in route:
            leg_miles = miles[previous][b]
            gas = int((distance + leg_miles) // gas_miles) - int(distance // gas_miles) if gas_miles else 0
            elapsed += hours[previous][b] + gas_hours * gas
            distance += leg_miles
            window = windows[b]
            if window:
                if elapsed < window[0]:
                    elapsed = window[0]
                elif elapsed > window[1]:
                    return math.inf
            elapsed += stop_hours
            previous = b
        leg_miles = miles[previous][0]
        gas = int((distance + leg_miles) // gas_miles) - int(distance // gas_miles) if gas_miles else 0
        return elapsed + hours[previous][0] + gas_hours * gas

    def timeline(self, route):
        """For [HQ] + route + [HQ]: when you arrive at each, how long you wait
        for it to open, and when you leave it."""
        hours, miles, windows = self.hours, self.miles, self.windows
        gas_miles, gas_hours = self.gas_miles, self.gas_hours
        arrive, wait, leave = [0.0], [0.0], [0.0]
        distance = 0
        stops = [0] + route + [0]
        for k in range(1, len(stops)):
            a, b = stops[k - 1], stops[k]
            leg_miles = miles[a][b]
            gas = int((distance + leg_miles) // gas_miles) - int(distance // gas_miles) if gas_miles else 0
            distance += leg_miles
            arrive.append(leave[-1] + hours[a][b] + gas_hours * gas)
            window = windows[b] if windows and b else None
            wait.append(max(0.0, window[0] - arrive[-1]) if window else 0.0)
            leave.append(arrive[-1] + wait[-1] + (self.stop_hours if k < len(stops) - 1 else 0))
        return arrive, wait, leave

    def route_points(self, route):
        points = self.points
        total = sum(points[i] for i in route)
        if self.combos:
            stops = set(route)
            total += sum(combo_points for _, combo_points, members in self.combos if members <= stops)
        return total

    def completing_points(self, route):
        """Points per place for adding it to the route: its own, plus any
        combo it would complete, being the last stop of one still missing."""
        if not self.combos:
            return self.points
        points = list(self.points)
        stops = set(route)
        for _, combo_points, members in self.combos:
            missing = members - stops
            if len(missing) == 1:
                points[next(iter(missing))] += combo_points
        return points

    def insert_cheapest(self, route, b):
        """The route with b inserted where it adds the least time, or None if
        it doesn't fit anywhere."""
        hours, k = min((self.route_hours(route[:k] + [b] + route[k:]), k)
                       for k in range(len(self.lead), len(route) + 1))
        return route[:k] + [b] + route[k:] if hours <= self.max_hours else None

    def only_route(self):
        """For --only: the --first stops, then the --must stops in the
        quickest order (trying every order of up to 8), ordered to bank points
        early where that still fits. Stops with an error if they don't fit."""
        rest = sorted(self.required - set(self.lead))
        if len(rest) <= 8:
            route = min((self.lead + list(order) for order in itertools.permutations(rest)), key=self.route_hours)
        else:
            route = self.combo_seed(())
        if route is None or self.route_hours(route) > self.max_hours:
            # Explains why, and how long they take
            self.must_route()
        return self.front_load_order(route)

    def must_route(self):
        """The quickest route through just the --first and --must stops: by
        inserting each where it adds the least time, or if that doesn't fit,
        by trying every order of up to 8 --must stops. Stops with an error
        saying how long they take if no order fits."""
        route = self.combo_seed(())
        if route is not None:
            return route
        rest = sorted(self.required - set(self.lead))
        with_first = " with the --first stops" if self.lead else ""
        if len(rest) > 8:
            sys.exit(f"ERROR: --must: those bonuses don't all fit in the time budget{with_first}")
        route = min((self.lead + list(order) for order in itertools.permutations(rest)), key=self.route_hours)
        hours = self.route_hours(route)
        if hours <= self.max_hours:
            return route
        if hours == math.inf:
            sys.exit(f"ERROR: --must: no order of those bonuses{with_first} makes all of their hours")
        sys.exit(f"ERROR: --must: those bonuses{with_first} take {hours:.2f} hours on their own, "
                 f"more than the {self.max_hours:g} hour budget (quickest order: "
                 f"{', '.join(self.places[b]['code'] for b in route)})")

    def combo_seed(self, combos):
        """A route through the --first stops, the --must stops and every stop
        of these combos, each inserted where it adds the least time (farthest
        from HQ first), or None if they can't all fit in the time budget."""
        route = list(self.lead)
        members = (set().union(*(members for _, _, members in combos)) | self.required) - set(route)
        for b in sorted(members, key=lambda b: (-self.hours[0][b], b)):
            route = self.insert_cheapest(route, b)
            if route is None:
                return None
        route = self.two_opt(route)
        return route if self.route_hours(route) <= self.max_hours else None

    def early_points(self, route):
        """Each bonus's points scaled by the fraction of the day left when you
        arrive, so the same stops score higher when big ones come first."""
        hours, miles, points, windows = self.hours, self.miles, self.points, self.windows
        gas_miles, gas_hours, stop_hours, max_hours = self.gas_miles, self.gas_hours, self.stop_hours, self.max_hours
        score = elapsed = distance = 0
        previous = 0
        for b in route:
            leg_miles = miles[previous][b]
            # Plus any gas stops on the way
            gas = int((distance + leg_miles) // gas_miles) - int(distance // gas_miles) if gas_miles else 0
            elapsed += hours[previous][b] + gas_hours * gas
            distance += leg_miles
            # The points count when you can take the photo, after any wait
            if windows is not None and windows[b] and elapsed < windows[b][0]:
                elapsed = windows[b][0]
            score += points[b] * (1 - elapsed / max_hours)
            elapsed += stop_hours
            previous = b
        return score

    def route_value(self, route):
        return self.route_points(route) + self.front_load * self.early_points(route)

    def orient(self, route):
        """Driving a loop backwards takes the same time, so pick the direction
        that collects points sooner."""
        if self.lead:
            # Reversing would move the --first stops to the end
            return route
        backwards = route[::-1]
        if self.windows is not None and self.route_hours(backwards) > self.max_hours:
            # Backwards misses a bonus's hours
            return route
        return backwards if self.early_points(backwards) > self.early_points(route) else route

    def insert_greedily(self, route, weight=1.0):
        """Keep adding the bonus with the best points per extra hour until nothing fits.

        weight sets how much extra time counts against a bonus: above 1 favors
        nearby bonuses, below 1 favors high-point ones farther away.
        """
        route = list(route)
        used = self.route_hours(route)
        used_miles = self.route_miles(route)
        unvisited = set(range(1, len(self.places))) - set(route)
        # This loop is where nearly all the run time goes, so it works from
        # local copies and does each piece of arithmetic once per pass
        hours, miles, hours_to, miles_to = self.hours, self.miles, self.hours_to, self.miles_to
        all_points, stop_hours, max_hours = self.points, self.stop_hours, self.max_hours
        gas_miles, gas_hours, front_load = self.gas_miles, self.gas_hours, self.front_load
        windows = self.windows
        # Insertions found not to fit when timed exactly; cleared after each insertion
        rejected = set()
        while True:
            best = None
            stops = [0] + route + [0]
            # The last missing stop of a combo is worth the combo's points too
            gain_points = self.completing_points(route)
            if windows is not None:
                # With bonus hours, an insertion fits if every later stop can
                # still make its hours and HQ by the end of the day. slack[k]
                # is how much later the photo at stop k could be taken; a
                # delay first uses up any wait at the next stop.
                arrive, wait, depart = self.timeline(route)
                slack = [0.0] * len(stops)
                slack[-1] = max_hours - arrive[-1]
                for k in range(len(stops) - 2, 0, -1):
                    window = windows[stops[k]]
                    limit = window[1] - (arrive[k] + wait[k]) if window else math.inf
                    slack[k] = min(limit, wait[k + 1] + slack[k + 1])
            elif front_load:
                # When you leave each stop
                depart = [0.0]
                for k in range(1, len(stops) - 1):
                    depart.append(depart[-1] + hours[stops[k - 1]][stops[k]] + stop_hours)
            if front_load:
                # The points still to collect after each stop
                later_points = [sum(all_points[s] for s in stops[k + 1:]) for k in range(len(stops) - 1)]
            gas_now = int(used_miles // gas_miles) if gas_miles else 0
            for k in range(len(self.lead), len(stops) - 1):
                a, c = stops[k], stops[k + 1]
                hours_from, miles_from, hours_into, miles_into = hours[a], miles[a], hours_to[c], miles_to[c]
                hours_ac, miles_ac = hours[a][c], miles[a][c]
                for b in unvisited:
                    extra_miles = miles_from[b] + miles_into[b] - miles_ac
                    extra = hours_from[b] + hours_into[b] - hours_ac + stop_hours
                    if gas_miles:
                        extra += gas_hours * (int((used_miles + extra_miles) // gas_miles) - gas_now)
                    if windows is None:
                        if used + extra > max_hours:
                            continue
                        photo = depart[k] + hours_from[b] if front_load else 0
                    else:
                        # Take b's photo once it's open, and check every later stop still fits
                        photo = depart[k] + hours_from[b]
                        window = windows[b]
                        if window:
                            if photo > window[1]:
                                continue
                            photo = max(photo, window[0])
                        gas_delay = (gas_hours * (int((used_miles + extra_miles) // gas_miles) - gas_now)
                                     if gas_miles else 0)
                        delay = photo + stop_hours + hours_into[b] + gas_delay - arrive[k + 1]
                        if delay - wait[k + 1] > slack[k + 1] or (b, k) in rejected:
                            continue
                    points = gain_points[b]
                    if front_load:
                        # Credit for reaching b early, minus the delay it causes every later stop
                        gain = (points * (1 + front_load * (1 - photo / max_hours))
                                - front_load * extra * later_points[k] / max_hours)
                    else:
                        gain = points
                    if gain <= 0:
                        continue
                    ratio = gain / max(extra, 1e-6) ** weight
                    # Ties go to the lowest index so the result never depends on set order
                    if best is None or ratio > best[0] or (ratio == best[0] and (-b, -k) > (best[1], best[2])):
                        best = (ratio, -b, -k, b, k, extra, extra_miles)
            if best is None:
                return route
            b, pos, extra, extra_miles = best[3:]
            if windows is not None:
                # The check above places gas stops roughly, so time it exactly
                candidate = route[:pos] + [b] + route[pos:]
                if self.timed_hours(candidate) > max_hours:
                    rejected.add((b, pos))
                    continue
                rejected.clear()
            route.insert(pos, b)
            used += extra
            used_miles += extra_miles
            unvisited.discard(b)

    def two_opt(self, route):
        """Uncross the route to cut driving time without changing which stops are in it."""
        if self.front_load:
            return self.two_opt_front_loaded(route)
        if self.windows is not None:
            return self.two_opt_timed(route)
        improved = True
        miles = self.route_miles(route)
        while improved:
            improved = False
            stops = [0] + route + [0]
            for i in range(1 + len(self.lead), len(stops) - 2):
                for j in range(i + 1, len(stops) - 1):
                    a, b, c, d = stops[i - 1], stops[i], stops[j], stops[j + 1]
                    # A slow zone can make a quicker leg longer in miles, so
                    # count any gas stop that adds
                    change_miles = self.miles[a][c] + self.miles[b][d] - self.miles[a][b] - self.miles[c][d]
                    change = (self.hours[a][c] + self.hours[b][d] - self.hours[a][b] - self.hours[c][d]
                              + self.gas_hours * (self.gas_stops(miles + change_miles) - self.gas_stops(miles)))
                    if change < -1e-9:
                        stops[i:j + 1] = reversed(stops[i:j + 1])
                        miles += change_miles
                        improved = True
            route = stops[1:-1]
        return route

    def two_opt_timed(self, route):
        """two_opt when bonuses have hours: time each reversal exactly, since
        it changes when every stop in it is reached."""
        improved = True
        hours = self.route_hours(route)
        while improved:
            improved = False
            for i in range(len(self.lead), len(route)):
                for j in range(i + 1, len(route)):
                    candidate = route[:i] + route[i:j + 1][::-1] + route[j + 1:]
                    c_hours = self.route_hours(candidate)
                    if c_hours < hours - 1e-9:
                        route, hours, improved = candidate, c_hours, True
        return route

    def two_opt_front_loaded(self, route):
        """Like two_opt, but keep a reversal that raises the value even if it
        drives farther, as long as the route still fits in the time budget."""
        improved = True
        while improved:
            improved = False
            value, hours = self.route_value(route), self.route_hours(route)
            for i in range(len(self.lead), len(route)):
                for j in range(i + 1, len(route)):
                    candidate = route[:i] + route[i:j + 1][::-1] + route[j + 1:]
                    c_value, c_hours = self.route_value(candidate), self.route_hours(candidate)
                    if c_hours <= self.max_hours and (c_value > value + 1e-9 or
                                                      (c_value > value - 1e-9 and c_hours < hours - 1e-9)):
                        route = candidate
                        improved = True
                        break
                if improved:
                    break
        return route

    def improve(self, route, weight=1.0):
        return self.orient(self.insert_greedily(self.two_opt(route), weight))

    def front_load_order(self, route):
        """Reorder the stops (reverse any stretch, or move one stop) to collect
        points sooner, as long as the route still fits in the time budget."""
        improved = True
        while improved:
            improved = False
            score = self.early_points(route)
            n, first = len(route), len(self.lead)
            moves = [route[:i] + route[i:j + 1][::-1] + route[j + 1:] for i in range(first, n) for j in range(i + 1, n)]
            # Take stop i out, then put it back at position j of what's left
            for i in range(first, n):
                rest = route[:i] + route[i + 1:]
                moves += [rest[:j] + [route[i]] + rest[j:] for j in range(first, n) if j != i]
            for candidate in moves:
                if self.early_points(candidate) > score + 1e-9 and self.route_hours(candidate) <= self.max_hours:
                    route = candidate
                    improved = True
                    break
        return route

    def better(self, a, b):
        """True if route a beats route b: higher value, then points collected
        sooner, then less time."""
        if self.windows is not None and self.route_hours(a) > self.max_hours:
            # Dropping stops can make a route miss a bonus's hours or run over
            return False
        if self.required:
            missing_a, missing_b = len(self.required - set(a)), len(self.required - set(b))
            if missing_a != missing_b:
                return missing_a < missing_b
        va, vb = self.route_value(a), self.route_value(b)
        if abs(va - vb) > 1e-9:
            return va > vb
        ea, eb = self.early_points(a), self.early_points(b)
        if abs(ea - eb) > 1e-9:
            return ea > eb
        return self.route_hours(a) < self.route_hours(b) - 1e-9

    def local_search(self, route, weight, max_drop):
        """Try dropping every run of 1..max_drop consecutive stops and rebuilding;
        take the first change that scores higher and start over, until none does."""
        improved = True
        while improved:
            improved = False
            for length in range(1, max_drop + 1):
                for start in range(len(self.lead), len(route) - length + 1):
                    if self.required.intersection(route[start:start + length]):
                        continue
                    candidate = self.improve(route[:start] + route[start + length:], weight)
                    if self.better(candidate, route):
                        route = candidate
                        improved = True
                        break
                if improved:
                    break
        return route

    def swap_search(self, route, weight):
        """Try replacing each stop with each unvisited bonus; take the first
        change that scores higher and start over, until none does."""
        improved = True
        while improved:
            improved = False
            unvisited = [b for b in range(1, len(self.places)) if b not in route]
            for i in range(len(self.lead), len(route)):
                if route[i] in self.required:
                    continue
                base = route[:i] + route[i + 1:]
                stops = [0] + base + [0]
                for b in unvisited:
                    _, pos = min((self.hours[stops[k]][b] + self.hours[b][stops[k + 1]]
                                  - self.hours[stops[k]][stops[k + 1]], k)
                                 for k in range(len(self.lead), len(stops) - 1))
                    candidate = base[:pos] + [b] + base[pos:]
                    if self.route_hours(candidate) > self.max_hours:
                        continue
                    candidate = self.improve(candidate, weight)
                    if self.better(candidate, route):
                        route = candidate
                        improved = True
                        break
                if improved:
                    break
        return route

    def search_from(self, start, weight, max_drop):
        return self.local_search(self.improve(self.insert_greedily(start, weight), weight), weight, max_drop)

    def solve(self, weights, max_drop, workers):
        if self.only:
            return self.only_route()
        # Start once from an empty route, then once from each bonus on its own,
        # so every bonus gets a chance to anchor the route. Skip bonuses too far
        # for a round trip, since nothing later would drop them from the route.
        # Any --first stops come before all of that, and every start already
        # has the --must stops, put where they add the least time.
        lead = self.lead
        base = self.must_route()
        starts = [base] + [route for route in (self.insert_cheapest(base, b) for b in range(1, len(self.places))
                                               if b not in base) if route is not None]
        # Inserting one bonus at a time rarely builds a whole combo, so also
        # start from every set of combos that fits, with all their stops
        for size in range(1, len(self.combos) + 1):
            for combos in itertools.combinations(self.combos, size):
                seed = self.combo_seed(combos)
                if seed is not None and seed not in starts:
                    starts.append(seed)
        tasks = [(start, weight, max_drop) for start in starts for weight in weights]
        best, best_weight = [], weights[0]
        started = time.monotonic()
        with multiprocessing.Pool(workers, initializer=_init_worker, initargs=(self,)) as pool:
            # imap returns results in task order, so the winner is the same
            # however many workers there are
            for n, (route, weight) in enumerate(pool.imap(_search_task, tasks), 1):
                if self.better(route, best):
                    best, best_weight = route, weight
                elapsed = time.monotonic() - started
                progress(f"Searching: {n} of {len(tasks)} starts ({n / len(tasks):.0%}), "
                         f"best so far {self.route_points(best)} points, {clock(elapsed)} elapsed, "
                         f"about {clock(elapsed / n * (len(tasks) - n))} left")

        # Polish the winner, alternating swaps and drops until neither helps
        polish = 1
        while True:
            progress(f"Polishing: pass {polish}, best so far {self.route_points(best)} points, "
                     f"{clock(time.monotonic() - started)} elapsed")
            route = self.local_search(self.swap_search(best, best_weight), best_weight, max_drop)
            if not self.better(route, best):
                break
            best = route
            polish += 1
        # Last, since the searches above reorder stops for shortest driving
        progress(f"Ordering stops to bank points early, {clock(time.monotonic() - started)} elapsed")
        best = self.front_load_order(best)
        progress(f"Search done: {self.route_points(best)} points in {clock(time.monotonic() - started)}")
        print(file=sys.stderr)
        if (len(set(best)) != len(best) or self.route_hours(best) > self.max_hours + 1e-9
                or best[:len(lead)] != lead or not self.required <= set(best)):
            sys.exit("ERROR: planner produced an invalid route (repeated bonus, over time, --first stops "
                     "moved or a --must stop missing); this is a bug")
        return best


# Each worker process gets its own copy of the planner once, rather than with every task
_worker_planner = None


def _init_worker(planner):
    global _worker_planner
    _worker_planner = planner
    # Exit when the pool is shut down early, even if the parent (such as the
    # web app's server) handles SIGTERM in a way that doesn't exit
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def _search_task(task):
    start, weight, max_drop = task
    return _worker_planner.search_from(start, weight, max_drop), weight


Leg = collections.namedtuple('Leg', 'place leg_miles miles arrive hours score gas wait combos')


def time_of_day(planner, hours):
    """Hours after the start as a clock time, e.g. 10:17."""
    minutes = round((clock_hours(planner.start) + hours) * 60)
    return f"{minutes // 60 % 24}:{minutes % 60:02}"


def route_legs(planner, route):
    """Yield a Leg for HQ, each stop, then HQ. arrive is when you get there,
    wait is how long until it opens, hours is when you leave after its
    picture, gas is how many gas stops were made on the way there, and
    combos is [(code, points)] for each combo that stop completes."""
    stops = [0] + route + [0]
    miles = hours = score = 0
    visited = set()
    for a, b in zip([None] + stops, stops):
        leg_miles = gas = 0
        if a is not None:
            leg_miles = planner.miles[a][b]
            gas = planner.gas_stops(miles + leg_miles) - planner.gas_stops(miles)
            miles += leg_miles
            hours += planner.hours[a][b] + gas * planner.gas_hours
        arrive = hours
        window = planner.windows[b] if planner.windows and b else None
        wait = max(0.0, window[0] - arrive) if window else 0.0
        hours += wait
        if a is not None and b != 0:
            hours += planner.stop_hours
        score += planner.places[b]['points']
        combos = []
        if b and b not in visited:
            visited.add(b)
            combos = [(code, points) for code, points, members in planner.combos if b in members and members <= visited]
            score += sum(points for _, points in combos)
        yield Leg(planner.places[b], leg_miles, miles, arrive, hours, score, gas, wait, combos)


def clock(seconds):
    """Seconds as m:ss, or h:mm:ss from an hour up, for progress lines."""
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def progress(text):
    """Rewrite the progress line on stderr; the padding clears a longer old line."""
    print(f"\r{text:<100}", end='', file=sys.stderr, flush=True)


def stamped_gpx_name(prefix, points):
    """A GPX file name with when it was made and the route's points, e.g.
    route-20261031-143005-11103pts.gpx, so one run never overwrites another."""
    return f"{prefix}-{datetime.now():%Y%m%d-%H%M%S}-{points}pts.gpx"


def write_gpx(planner, route, gpx_file_path):
    """Write the stops as waypoints plus a route through them in order, for
    Garmin BaseCamp and GPS units. Each stop's comment holds its points."""
    ET.register_namespace('', GPX_NS)
    gpx = ET.Element(f'{{{GPX_NS}}}gpx', version='1.1', creator='planRoute.py')

    def add_point(parent, tag, leg, n):
        place = leg.place
        point = ET.SubElement(parent, f'{{{GPX_NS}}}{tag}', lat=f"{place['lat']:.6f}", lon=f"{place['lon']:.6f}")
        ET.SubElement(point, f'{{{GPX_NS}}}name').text = place['code']
        ET.SubElement(point, f'{{{GPX_NS}}}cmt').text = f"{place['points']} points"
        gas = f", {leg.gas} gas stop{'s' if leg.gas > 1 else ''} before" if leg.gas else ''
        wait = f", wait {leg.wait * 60:.0f} min for it to open at {place['opens']}" if leg.wait else ''
        wait += ''.join(f", completes {code} combo (+{points})" for code, points in leg.combos)
        if n == 0:
            when = f"Start, {place['state']}, leave at hour 0 ({time_of_day(planner, 0)})"
        elif n > len(route):
            when = (f"Finish, {place['state']}, arrive by hour {leg.arrive:.2f} "
                    f"({time_of_day(planner, leg.arrive)}){gas}")
        else:
            when = (f"Stop {n} of {len(route)}, {place['state']}, leave by hour {leg.hours:.2f} "
                    f"({time_of_day(planner, leg.hours)}){gas}{wait}")
        ET.SubElement(point, f'{{{GPX_NS}}}desc').text = when

    legs = list(route_legs(planner, route))
    # The waypoint list holds HQ once; the route visits it at both ends
    for n, leg in enumerate(legs[:-1]):
        add_point(gpx, 'wpt', leg, n)
    last = legs[-1]
    rte = ET.SubElement(gpx, f'{{{GPX_NS}}}rte')
    ET.SubElement(rte, f'{{{GPX_NS}}}name').text = f"Rally route {last.score} points"
    ET.SubElement(rte, f'{{{GPX_NS}}}desc').text = (
        f"{len(route)} bonuses, {last.miles:.0f} estimated miles, "
        f"{planner.gas_stops(last.miles)} gas stop{'' if planner.gas_stops(last.miles) == 1 else 's'}, "
        f"{last.hours:.2f} of {planner.max_hours} hours")
    for n, leg in enumerate(legs):
        add_point(rte, 'rtept', leg, n)

    ET.indent(gpx)
    ET.ElementTree(gpx).write(gpx_file_path, encoding='utf-8', xml_declaration=True)


def leg_notes(planner, leg):
    """Notes for one stop in the route table: gas stops, waits, hours and combos."""
    notes = []
    if leg.gas:
        notes.append(f"+ {leg.gas} gas stop{'s' if leg.gas > 1 else ''} on the way")
    if leg.wait:
        notes.append(f"waits {leg.wait * 60:.0f} min to open at {leg.place['opens']}")
    elif leg.place.get('opens') and planner.windows:
        notes.append(f"open {leg.place['opens']}-{leg.place['closes']}")
    notes += [f"completes {code} combo +{points}" for code, points in leg.combos]
    return notes


def summary_lines(planner, route, legs):
    """The lines printed under the route table: totals, combos and points banked."""
    last = legs[-1]
    places = planner.places
    lines = [f"Bonuses: {len(route)}   Points: {last.score}   Miles: {last.miles:.0f}   "
             f"Gas stops: {planner.gas_stops(last.miles)}   Hours: {last.hours:.2f} of {planner.max_hours}",
             f"States: {len(set(places[i]['state'] for i in route))}   "
             f"Points per mile: {last.score / last.miles if last.miles else 0:.1f}"]
    if planner.combos:
        done = [combo for leg in legs for combo in leg.combos]
        stops = set(route)
        partial = [f"{code} {len(members & stops)} of {len(members)}" for code, _, members in planner.combos
                   if members & stops and not members <= stops]
        lines.append(f"Combos: " + (", ".join(f"{code} +{points}" for code, points in done) or "none")
                     + f" ({sum(points for _, points in done)} points)"
                     + (f"; partly visited, not scored: {', '.join(partial)}" if partial else ''))

    # How many points are already banked if the day is cut short
    banked = []
    for fraction in (0.25, 0.5, 0.75):
        cutoff = planner.max_hours * fraction
        # Scores only go up along the route, combos counting when completed
        got = max(leg.score for leg in legs if leg.arrive + leg.wait <= cutoff)
        banked.append(f"{got} ({got / last.score:.0%}) by hour {cutoff:g}" if last.score else f"0 by hour {cutoff:g}")
    lines.append("Banked: " + ", ".join(banked))
    return lines


def print_route(planner, route):
    print(f"{'#':>3}  {'Bonus':<24} {'State':<5} {'Points':>6} {'Leg mi':>7} {'Total mi':>8} {'Hours':>6} "
          f"{'Arrive':>6} {'Score':>6}")
    legs = list(route_legs(planner, route))
    for n, leg in enumerate(legs):
        notes = leg_notes(planner, leg)
        print(f"{n:>3}  {leg.place['code']:<24} {leg.place['state']:<5} {leg.place['points']:>6} "
              f"{leg.leg_miles:>7.1f} {leg.miles:>8.1f} {leg.hours:>6.2f} {time_of_day(planner, leg.arrive):>6} "
              f"{leg.score:>6}{'  ' + '; '.join(notes) if notes else ''}")
    print()
    for line in summary_lines(planner, route, legs):
        print(line)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('csv_file', nargs='?', default='bonus-lat-lon-points.csv')
    parser.add_argument('--hours', type=float, default=9.5, help='time budget in hours (default 9.5)')
    parser.add_argument('--speed', type=float, default=45, help='average speed in MPH (default 45)')
    parser.add_argument('--stop-minutes', type=float, default=5,
                        help='time spent at each bonus taking its picture (default 5)')
    parser.add_argument('--road-factor', type=float, default=1.0,
                        help='multiply straight-line miles by this to approximate road miles (default 1.0)')
    parser.add_argument('--max-drop', type=int, default=6,
                        help='longest run of stops the search tries dropping at once; more is slower (default 6)')
    parser.add_argument('--front-load', type=float, default=0,
                        help='favor collecting points early in the day: each bonus counts as its points x '
                             '(1 + FRONT_LOAD x fraction of the day left on arrival). 0 keeps the highest total '
                             'and just orders it to bank points early; 1 trades some total for earlier points '
                             '(default 0)')
    parser.add_argument('--workers', type=int, default=os.cpu_count(),
                        help=f'CPU cores to search with (default all, {os.cpu_count()} here)')
    parser.add_argument('--quick', action='store_true',
                        help="plan with planRouteSearch.py's beam search instead: about 4x faster and as good "
                             "on the 2026 bonuses, but may miss a better route on other data; no --front-load")
    parser.add_argument('--gpx',
                        help='also write the route as GPX for Garmin BaseCamp and GPS units '
                             '(default route-DATE-TIME-POINTSpts.gpx)')
    add_slow_zone_args(parser)
    add_gas_args(parser)
    add_first_args(parser)
    add_hours_args(parser)
    add_combo_args(parser)
    args = parser.parse_args()

    hq, bonuses = load_bonuses(args.csv_file)
    slow_zones = slow_zones_from_args(args)
    planner = Planner(hq, bonuses, args.hours, args.speed, args.stop_minutes, args.road_factor, args.front_load,
                      slow_zones, args.gas_miles, args.gas_minutes, args.start, not args.ignore_hours)
    apply_first(planner, args)
    apply_combos(planner, args)
    if args.quick:
        if args.front_load:
            sys.exit("ERROR: --quick doesn't support --front-load")
        import planRouteSearch
        route = planRouteSearch.quick_route(planner, max(1, args.workers))
    else:
        route = planner.solve(START_WEIGHTS, args.max_drop, max(1, args.workers))
    print(f"{len(bonuses)} bonuses, {args.hours} hours at {args.speed} MPH, "
          f"{args.stop_minutes:g} min per stop, road factor {args.road_factor:g}, "
          f"front-load {args.front_load:g}" + (", quick (beam search)" if args.quick else ""))
    print(f"{describe_gas(args)}, {describe_slow_zones(slow_zones)}, {describe_first(planner)}")
    print(f"{describe_hours(planner)}")
    print(f"{describe_combos(planner)}\n")
    print_route(planner, route)
    gpx = args.gpx or stamped_gpx_name('route', planner.route_points(route))
    write_gpx(planner, route, gpx)
    print(f"\nGPX written to {gpx}")


if __name__ == "__main__":
    main()
