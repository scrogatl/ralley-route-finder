#!/usr/bin/env python
"""
Check a planned route against real roads with the Google Maps Routes API.

Reads the route from a GPX file written by planRoute.py or planRouteExact.py
(the newest one by default), asks Google for driving directions through the stops
in that order, and prints each leg's road miles and driving time, when you'd
arrive at and leave each stop, and whether the day still fits in the time
budget. It also prints a --road-factor and --speed for planRoute.py that
match Google's numbers, so the next plan can be closer to the real roads.

Stops are counted the same way as planRoute.py: --stop-minutes at each bonus
and --gas-minutes for every --gas-miles driven. Bonuses with hours (from the
rally book, in bonus-lat-lon-points.csv) are waited for if reached before
they open, and reported as missed if reached after they close. Combo
bonuses (bonus-combos.csv) score when every bonus in one is made in time.

Without --depart, the whole route goes in one request per 25 stops and the
times have no traffic. With --depart, each leg is its own request, leaving
when you'd leave that stop, and the times include Google's traffic forecast.

If the route is over time or misses a bonus's hours on Google's times, it
also looks for stops to drop so the rest fits, keeping the most points, and
writes that route as route-fit-DATE-TIME-POINTSpts.gpx to check next. Legs
that skip a dropped stop are estimated from Google's legs around them, so
check the fitted route with Google before riding it.

Google's times are for driving at about the usual speed. --highway-faster and
--surface-faster drive that many percent faster (or slower, if negative):
each turn-by-turn step Google averages --highway-mph or more on counts as
highway, every other step as surface streets. Traffic delays aren't changed.

Needs GMAPS_API_KEY in the environment, for a Google Cloud project with the
Routes API turned on. A check is usually inside Google's free monthly usage.

    python checkRoute.py --depart "2026-11-07 07:00"
"""
import argparse, collections, glob, os, sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import requests
import planRoute

GPX_NS = planRoute.GPX_NS
METERS_PER_MILE = 1609.344
ROUTES_URL = 'https://routes.googleapis.com/directions/v2:computeRoutes'
# Ask only for what's used; Google requires this list and bills by it
FIELD_MASK = 'routes.legs.distanceMeters,routes.legs.duration,routes.polyline.encodedPolyline'
# Each step's miles and no-traffic time, to drive faster than Google's times
STEPS_FIELD_MASK = FIELD_MASK + ',routes.legs.steps.distanceMeters,routes.legs.steps.staticDuration'
# A step Google drives at this speed or more counts as highway
HIGHWAY_MPH = 55
# Google takes up to 25 stops between the start and end of one request
MAX_WAYPOINTS = 25


def newest_route():
    """The most recent GPX file from planRoute.py or planRouteExact.py in
    this folder (not one this script wrote)."""
    files = [f for f in glob.glob('route*.gpx') if not f.startswith('route-google')]
    if not files:
        sys.exit("ERROR: no route*.gpx file here; make one with planRoute.py, or name the GPX file to check")
    return max(files, key=os.path.getmtime)


def load_route(gpx_file_path):
    """Return the route's points in order, Rally HQ to Rally HQ; each is a
    dict with code, lat, lon, points, state."""
    rte = ET.parse(gpx_file_path).getroot().find(f'{{{GPX_NS}}}rte')
    if rte is None:
        sys.exit(f"ERROR: no route found in {gpx_file_path}; make one with planRoute.py")
    places = []
    for point in rte.findall(f'{{{GPX_NS}}}rtept'):
        # planRoute.py writes "630 points" in cmt and "Stop 1 of 11, GA, ..." in desc
        cmt = point.findtext(f'{{{GPX_NS}}}cmt', '0').split()
        desc = point.findtext(f'{{{GPX_NS}}}desc', '').split(',')
        places.append(dict(code=point.findtext(f'{{{GPX_NS}}}name', '').strip(),
                           lat=float(point.get('lat')), lon=float(point.get('lon')),
                           points=int(cmt[0]) if cmt and cmt[0].isdigit() else 0,
                           state=desc[1].strip() if len(desc) > 1 else ''))
    if len(places) < 2:
        sys.exit(f"ERROR: the route in {gpx_file_path} has fewer than 2 points")
    return places


def waypoint(place):
    return {'location': {'latLng': {'latitude': place['lat'], 'longitude': place['lon']}}}


def seconds(duration):
    """Google writes durations as "123s"."""
    return float(duration.rstrip('s'))


def leg_result(leg, faster=None):
    """Road miles and driving hours for one leg of a Routes response. With
    traffic on, the duration includes Google's traffic forecast. faster is
    (highway percent, surface percent, highway mph) to drive faster than
    Google: each step's no-traffic time is cut by its percent, and any
    traffic delay is left as it is."""
    hours = seconds(leg['duration']) / 3600
    if faster:
        highway, surface, highway_mph = faster
        for step in leg.get('steps', []):
            step_hours = seconds(step.get('staticDuration', '0s')) / 3600
            if step_hours:
                step_mph = step.get('distanceMeters', 0) / METERS_PER_MILE / step_hours
                percent = highway if step_mph >= highway_mph else surface
                hours -= step_hours - step_hours / (1 + percent / 100)
    return leg.get('distanceMeters', 0) / METERS_PER_MILE, hours


def describe_faster(faster):
    """E.g. "highways (55+ mph) 10% faster, other roads 5% faster"."""
    highway, surface, highway_mph = faster

    def change(percent):
        return f"{abs(percent):g}% {'faster' if percent > 0 else 'slower'}" if percent else "at Google's speed"
    return f"highways ({highway_mph:g}+ mph) {change(highway)}, other roads {change(surface)}"


def make_faster(highway, surface, highway_mph=HIGHWAY_MPH):
    """The faster argument for the fetch functions, or None when both are 0."""
    if not -50 <= highway <= 100 or not -50 <= surface <= 100:
        sys.exit("ERROR: the faster percents must be from -50 to 100")
    return (highway, surface, highway_mph) if highway or surface else None


def directions(api_key, places, depart=None, steps=False):
    """Ask the Routes API for the driving route through places in order;
    with depart (a datetime), use the traffic forecast for that time; with
    steps, include each leg's turn-by-turn steps."""
    body = {'origin': waypoint(places[0]), 'destination': waypoint(places[-1]),
            'intermediates': [waypoint(p) for p in places[1:-1]], 'travelMode': 'DRIVE'}
    if depart:
        body['routingPreference'] = 'TRAFFIC_AWARE'
        body['departureTime'] = depart.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    else:
        body['routingPreference'] = 'TRAFFIC_UNAWARE'
    response = requests.post(ROUTES_URL, json=body, timeout=60,
                             headers={'X-Goog-Api-Key': api_key,
                                      'X-Goog-FieldMask': STEPS_FIELD_MASK if steps else FIELD_MASK})
    if not response.ok:
        try:
            message = response.json()['error']['message']
        except (ValueError, KeyError):
            message = response.text
        sys.exit(f"ERROR: Google Routes API: {response.status_code} {message}")
    routes = response.json().get('routes')
    if not routes:
        sys.exit(f"ERROR: Google found no driving route from {places[0]['code']} to {places[-1]['code']}")
    return routes[0]


def decode_polyline(text):
    """Decode Google's encoded polyline format into [(lat, lon)]."""
    points, index, lat, lon = [], 0, 0, 0
    while index < len(text):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(text[index]) - 63
                index += 1
                result |= (byte & 0x1f) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append((lat / 1e5, lon / 1e5))
    return points


def fetch_batched(api_key, places, faster=None):
    """One request per 25 stops; no traffic. Returns ([(miles, hours)] per leg, [polyline])."""
    legs, polylines = [], []
    start = 0
    while start < len(places) - 1:
        # Each request ends where the next one starts
        end = min(start + MAX_WAYPOINTS + 1, len(places) - 1)
        route = directions(api_key, places[start:end + 1], steps=bool(faster))
        legs += [leg_result(leg, faster) for leg in route['legs']]
        polylines.append(route['polyline']['encodedPolyline'])
        start = end
    return legs, polylines


def fetch_with_traffic(api_key, places, depart, stop_hours, gas_miles, gas_hours, windows, faster=None):
    """One request per leg, leaving when you'd leave that stop, so each leg
    gets the traffic forecast for its time of day."""
    legs, polylines = [], []
    elapsed = miles = 0
    for n, (a, b) in enumerate(zip(places, places[1:])):
        print(f"\rAsking Google: leg {n + 1} of {len(places) - 1}", end='', file=sys.stderr, flush=True)
        route = directions(api_key, [a, b], depart + timedelta(hours=elapsed), steps=bool(faster))
        leg_miles, leg_hours = leg_result(route['legs'][0], faster)
        legs.append((leg_miles, leg_hours))
        polylines.append(route['polyline']['encodedPolyline'])
        gas = gas_stops(miles + leg_miles, gas_miles) - gas_stops(miles, gas_miles)
        miles += leg_miles
        elapsed += leg_hours + gas * gas_hours
        # Wait for it to open, as timeline() does
        window = windows.get(b['code'])
        if window and elapsed < window[0]:
            elapsed = window[0]
        elapsed += stop_hours
    print(file=sys.stderr)
    return legs, polylines


def gas_stops(miles, gas_miles):
    return int(miles // gas_miles) if gas_miles else 0


Row = collections.namedtuple('Row', 'place leg_miles miles leg_hours arrive wait leave score gas missed combos')


def bonus_windows(csv_file_path, start):
    """{code: (opens, closes, opens text, closes text)}, the first two in
    hours after the start, for bonuses with hours in the bonus file; empty
    if there's no file."""
    if not os.path.exists(csv_file_path):
        return {}
    _, bonuses = planRoute.load_bonuses(csv_file_path)
    begin = planRoute.clock_hours(start)
    return {b['code']: (planRoute.clock_hours(b['opens']) - begin, planRoute.clock_hours(b['closes']) - begin,
                        b['opens'], b['closes'])
            for b in bonuses if b.get('opens')}


def timeline(places, legs, stop_hours, gas_miles, gas_hours, windows, combos=()):
    """Yield a Row for HQ, each stop, then HQ. A bonus reached before it opens
    is waited for; one reached after it closes is missed and scores nothing.
    combos is [(code, points, member codes)]; each Row's combos are the
    (code, points) that stop completes."""
    miles = hours = score = 0
    scored = set()
    yield Row(places[0], 0, 0, 0, 0, 0, 0, 0, 0, False, [])
    for n, (place, (leg_miles, leg_hours)) in enumerate(zip(places[1:], legs), 1):
        gas = gas_stops(miles + leg_miles, gas_miles) - gas_stops(miles, gas_miles)
        miles += leg_miles
        hours += leg_hours + gas * gas_hours
        arrive = hours
        window = windows.get(place['code'])
        wait = max(0.0, window[0] - arrive) if window else 0.0
        missed = bool(window) and arrive > window[1]
        hours += wait
        # No picture to take back at Rally HQ
        if n < len(places) - 1:
            hours += stop_hours
        completed = []
        if not missed and place['code'] not in scored:
            score += place['points']
            scored.add(place['code'])
            completed = [(code, points) for code, points, members in combos
                         if place['code'] in members and scored.issuperset(members)]
            score += sum(points for _, points in completed)
        yield Row(place, leg_miles, miles, leg_hours, arrive, wait, hours, score, gas, missed, completed)


def row_notes(row, windows):
    """Notes for one stop: gas stops on the way, its hours and any combo it completes."""
    notes = []
    if row.gas:
        notes.append(f"+ {row.gas} gas stop{'s' if row.gas > 1 else ''} on the way")
    window = windows.get(row.place['code'])
    if row.missed:
        notes.append(f"MISSED: closes {window[3]}")
    elif row.wait:
        notes.append(f"waits {row.wait * 60:.0f} min to open at {window[2]}")
    elif window:
        notes.append(f"open {window[2]}-{window[3]}")
    notes += [f"completes {code} combo +{points}" for code, points in row.combos]
    return notes


def summary_lines(places, legs, rows, windows, combos, max_hours, gas_miles, time_of_day,
                  leg_minutes=planRoute.LEG_MINUTES):
    """The lines under the table: totals, missed hours, combos, whether it
    fits, and the --road-factor and --speed that match Google's numbers with
    leg_minutes on each leg."""
    last = rows[-1]
    miles, hours, points = last.miles, last.arrive, last.score
    line_miles = sum(planRoute.haversine_miles(a, b) for a, b in zip(places, places[1:]))
    # Driving time less the planner's minutes per leg, which aren't driven at --speed
    moving = sum(1 for a, b in zip(places, places[1:]) if planRoute.haversine_miles(a, b) > planRoute.SAME_PLACE_MILES)
    drive_hours = sum(h for _, h in legs) - moving * leg_minutes / 60
    lines = [f"Bonuses: {len(places) - 2}   Points: {points}   Road miles: {miles:.0f}   "
             f"Gas stops: {gas_stops(miles, gas_miles)}   Hours: {hours:.2f} of {max_hours}"]
    missed = [row for row in rows if row.missed]
    if missed:
        lost = sum(row.place['points'] for row in missed)
        lines.append(f"MISSED HOURS: " + ", ".join(f"{row.place['code']} (arrive {time_of_day(row.arrive)}, "
                                                   f"closes {windows[row.place['code']][3]})" for row in missed)
                     + f"; {lost} points not counted")
    if combos:
        done = [combo for row in rows for combo in row.combos]
        planned = {p['code'] for p in places}
        # Combos the plan had every bonus of, lost to a missed bonus
        lost = [code for code, _, members in combos
                if planned.issuperset(members) and code not in {c for c, _ in done}]
        lines.append("Combos: " + (", ".join(f"{code} +{points}" for code, points in done) or "none")
                     + (f"; LOST to missed hours: {', '.join(lost)}" if lost else ''))
    if hours <= max_hours:
        lines.append(f"FITS: back at Rally HQ with {(max_hours - hours) * 60:.0f} minutes to spare")
    else:
        late = [row.place['code'] for row in rows[1:-1] if row.leave > max_hours]
        lines.append(f"OVER by {(hours - max_hours) * 60:.0f} minutes. Stops you'd leave after time runs out: "
                     f"{', '.join(late) or 'none (only the drive back is late)'}")
    if line_miles and drive_hours > 0:
        lines.append(f"To plan closer to these roads: planRoute.py --road-factor {miles / line_miles:.2f} "
                     f"--speed {miles / drive_hours:.0f} --leg-minutes {leg_minutes:g}")
    return lines


# How many partly dropped routes fit_to_time keeps at each step
FIT_BEAM = 60


def fit_to_time(places, legs, stop_hours, gas_miles, gas_hours, windows, combos, max_hours,
                leg_minutes=planRoute.LEG_MINUTES):
    """Find stops to drop so the route fits max_hours on Google's times and
    makes its bonuses' hours, keeping the most points. Returns (places, legs)
    for the fitted route, or None if dropping stops doesn't score more.

    A leg Google drove is kept as it is. A leg that skips dropped stops is
    the planner's estimate for it (straight line, slow zones and leg minutes)
    scaled by how Google's time and miles compared with the planner's over
    the legs it replaces. Beam search: drop one more stop at a time, keeping
    the FIT_BEAM best routes, those over time ranked by points less a charge
    for each hour over."""
    zones = [planRoute.ATLANTA_SLOW_ZONE, planRoute.ATHENS_SLOW_ZONE]

    def estimate(a, b):
        line = planRoute.haversine_miles(a, b)
        extra = leg_minutes / 60 if line > planRoute.SAME_PLACE_MILES else 0
        return line, planRoute.Planner.leg_hours(a, b, line, 60, zones) + extra

    # Running totals over the legs, so any skipped run is two lookups
    totals = [(0, 0, 0, 0)]
    for (a, b), (miles, hours) in zip(zip(places, places[1:]), legs):
        line, model = estimate(a, b)
        last = totals[-1]
        totals.append((last[0] + miles, last[1] + hours, last[2] + line, last[3] + model))

    def leg(i, j):
        if j == i + 1:
            return legs[i]
        miles, hours, line, model = (totals[j][k] - totals[i][k] for k in range(4))
        new_line, new_model = estimate(places[i], places[j])
        return (new_line * miles / line if line else miles), (new_model * hours / model if model else hours)

    def evaluate(keep):
        stops = (0,) + keep + (len(places) - 1,)
        route_legs = [leg(i, j) for i, j in zip(stops, stops[1:])]
        last = list(timeline([places[k] for k in stops], route_legs, stop_hours, gas_miles, gas_hours,
                             windows, combos))[-1]
        return last.score, last.arrive, route_legs

    full = tuple(range(1, len(places) - 1))
    points, hours, _ = evaluate(full)
    best = (points, -hours, full) if hours <= max_hours else None
    # Points an hour over is worth giving up, to rank routes still over time
    charge = 2 * points / max(hours, 1)
    beam, seen = [full], {full}
    while beam:
        ranked = []
        for keep in beam:
            for k in range(len(keep)):
                child = keep[:k] + keep[k + 1:]
                if child in seen:
                    continue
                seen.add(child)
                points, hours, _ = evaluate(child)
                ranked.append((points - max(0, hours - max_hours) * charge, points, -hours, child))
                if hours <= max_hours and (best is None or (points, -hours) > best[:2]):
                    best = (points, -hours, child)
        ranked.sort(reverse=True)
        # Once every route kept fits, dropping more only loses points
        if not ranked or (best and all(-r[2] <= max_hours for r in ranked[:FIT_BEAM])
                          and ranked[0][1] <= best[0]):
            break
        beam = [r[3] for r in ranked[:FIT_BEAM]]
    if best is None or best[2] == full:
        return None
    keep = (0,) + best[2] + (len(places) - 1,)
    return [places[k] for k in keep], evaluate(best[2])[2]


def write_gpx(rows, polylines, max_hours, source, gpx_file_path):
    """The stops as waypoints and a route, as planRoute.py writes them but with
    Google's times, plus a track along the roads Google chose."""
    ET.register_namespace('', GPX_NS)
    gpx = ET.Element(f'{{{GPX_NS}}}gpx', version='1.1', creator='checkRoute.py')
    stops = len(rows) - 2

    def add_point(parent, tag, row, n):
        place, arrive, leave, gas = row.place, row.arrive, row.leave, row.gas
        point = ET.SubElement(parent, f'{{{GPX_NS}}}{tag}', lat=f"{place['lat']:.6f}", lon=f"{place['lon']:.6f}")
        ET.SubElement(point, f'{{{GPX_NS}}}name').text = place['code']
        ET.SubElement(point, f'{{{GPX_NS}}}cmt').text = f"{place['points']} points"
        gas = f", {gas} gas stop{'s' if gas > 1 else ''} before" if gas else ''
        if n == 0:
            when = f"Start, {place['state']}, leave at hour 0"
        elif n > stops:
            when = f"Finish, {place['state']}, arrive by hour {arrive:.2f}{gas}"
        else:
            when = f"Stop {n} of {stops}, {place['state']}, leave by hour {leave:.2f}{gas}"
            if row.missed:
                when += ", MISSED: closed before you'd get there"
            elif row.wait:
                when += f", wait {row.wait * 60:.0f} min for it to open"
            when += ''.join(f", completes {code} combo (+{points})" for code, points in row.combos)
        ET.SubElement(point, f'{{{GPX_NS}}}desc').text = when

    for n, row in enumerate(rows[:-1]):
        add_point(gpx, 'wpt', row, n)
    last = rows[-1]
    summary = f"{stops} bonuses, {last.miles:.0f} road miles, {last.arrive:.2f} of {max_hours} hours ({source})"
    rte = ET.SubElement(gpx, f'{{{GPX_NS}}}rte')
    ET.SubElement(rte, f'{{{GPX_NS}}}name').text = f"Rally route {last.score} points"
    ET.SubElement(rte, f'{{{GPX_NS}}}desc').text = summary
    for n, row in enumerate(rows):
        add_point(rte, 'rtept', row, n)
    # A fitted route has no Google roads yet, so no track
    if polylines:
        trk = ET.SubElement(gpx, f'{{{GPX_NS}}}trk')
        ET.SubElement(trk, f'{{{GPX_NS}}}name').text = f"Rally roads {last.score} points"
        ET.SubElement(trk, f'{{{GPX_NS}}}desc').text = summary
    for polyline in polylines:
        segment = ET.SubElement(trk, f'{{{GPX_NS}}}trkseg')
        for lat, lon in decode_polyline(polyline):
            ET.SubElement(segment, f'{{{GPX_NS}}}trkpt', lat=f"{lat:.6f}", lon=f"{lon:.6f}")

    ET.indent(gpx)
    ET.ElementTree(gpx).write(gpx_file_path, encoding='utf-8', xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('gpx_file', nargs='?', help='GPX file to check (default the newest route*.gpx here)')
    parser.add_argument('--hours', type=float, default=9.5, help='time budget in hours (default 9.5)')
    parser.add_argument('--stop-minutes', type=float, default=5,
                        help='time spent at each bonus taking its picture (default 5)')
    parser.add_argument('--depart', type=datetime.fromisoformat,
                        help='when you leave Rally HQ, e.g. "2026-11-07 07:00" (your computer\'s time zone '
                             'unless you add one, e.g. "2026-11-07 07:00-05:00"); uses Google\'s traffic forecast. '
                             'Without it, times have no traffic')
    parser.add_argument('--gpx',
                        help='write the route with Google\'s times and roads as GPX '
                             '(default route-google-DATE-TIME-POINTSpts.gpx)')
    parser.add_argument('--bonuses', default='bonus-lat-lon-points.csv',
                        help='bonus file with the hours bonuses are open (default bonus-lat-lon-points.csv)')
    parser.add_argument('--start', default=planRoute.RALLY_START, type=planRoute.start_time,
                        help=f'rally start time, HH:MM, for bonus hours (default {planRoute.RALLY_START}, '
                             f'or the time of --depart)')
    parser.add_argument('--combos', default='bonus-combos.csv',
                        help='combo bonuses from the rally book (default bonus-combos.csv, if it exists)')
    parser.add_argument('--highway-faster', type=float, default=0, metavar='PERCENT',
                        help='drive this many percent faster than Google on highways, or slower if negative '
                             '(default 0)')
    parser.add_argument('--surface-faster', type=float, default=0, metavar='PERCENT',
                        help='the same for every other road (default 0)')
    parser.add_argument('--leg-minutes', type=float, default=planRoute.LEG_MINUTES,
                        help='the planner\'s minutes per leg: for the --speed it suggests, and to estimate legs '
                             f'that skip a dropped stop (default {planRoute.LEG_MINUTES})')
    parser.add_argument('--highway-mph', type=float, default=HIGHWAY_MPH,
                        help=f'a step Google drives at this speed or more is highway (default {HIGHWAY_MPH})')
    planRoute.add_gas_args(parser)
    args = parser.parse_args()

    args.gpx_file = args.gpx_file or newest_route()
    places = load_route(args.gpx_file)
    stop_hours, gas_hours = args.stop_minutes / 60, args.gas_minutes / 60
    start = f"{args.depart:%H:%M}" if args.depart else args.start
    windows = bonus_windows(args.bonuses, start)
    if args.depart and args.depart.timestamp() < datetime.now().timestamp():
        sys.exit("ERROR: --depart is in the past; Google only forecasts traffic for future times")
    faster = make_faster(args.highway_faster, args.surface_faster, args.highway_mph)
    api_key = os.environ.get('GMAPS_API_KEY') or sys.exit("ERROR: set GMAPS_API_KEY to your Google Maps API key")
    if args.depart:
        legs, polylines = fetch_with_traffic(api_key, places, args.depart, stop_hours, args.gas_miles, gas_hours,
                                             windows, faster)
        source = f"Google, with traffic, leaving {args.depart:%a %b %d %H:%M}"
    else:
        legs, polylines = fetch_batched(api_key, places, faster)
        source = "Google, no traffic"
    if faster:
        source += f", {describe_faster(faster)}"
    combos = planRoute.load_combos(args.combos)
    rows = list(timeline(places, legs, stop_hours, args.gas_miles, gas_hours, windows, combos))
    begin = planRoute.clock_hours(start)

    def time_of_day(hours):
        minutes = round((begin + hours) * 60)
        return f"{minutes // 60 % 24}:{minutes % 60:02}"

    print(f"{args.gpx_file}: {len(places) - 2} bonuses, {source}")
    print(f"{args.stop_minutes:g} min per stop, {planRoute.describe_gas(args)}, start {start}, "
          + (f"bonus hours from {args.bonuses}" if windows else "no bonus hours") + "\n")
    print(f"{'#':>3}  {'Bonus':<24} {'State':<5} {'Points':>6} {'Line mi':>7} {'Road mi':>7} {'Total mi':>8} {'Drive':>6} "
          f"{'Arrive':>6} {'Leave':>6} {'Time':>6} {'Score':>6}")
    for n, row in enumerate(rows):
        place = row.place
        straight = planRoute.haversine_miles(rows[n - 1].place, place) if n else 0
        notes = row_notes(row, windows)
        print(f"{n:>3}  {place['code']:<24} {place['state']:<5} {place['points']:>6} {straight:>7.1f} "
              f"{row.leg_miles:>7.1f} {row.miles:>8.1f} {row.leg_hours * 60:>4.0f} m {row.arrive:>6.2f} "
              f"{row.leave:>6.2f} {time_of_day(row.arrive):>6} {row.score:>6}{'  ' + '; '.join(notes) if notes else ''}")

    print()
    for line in summary_lines(places, legs, rows, windows, combos, args.hours, args.gas_miles, time_of_day,
                              args.leg_minutes):
        print(line)
    points = rows[-1].score
    gpx = args.gpx or planRoute.stamped_gpx_name('route-google', points)
    write_gpx(rows, polylines, args.hours, source, gpx)
    print(f"\nGPX written to {gpx}")

    fitted = fit_to_time(places, legs, stop_hours, args.gas_miles, gas_hours, windows, combos, args.hours,
                         args.leg_minutes)
    if fitted:
        fit_places, fit_legs = fitted
        fit_rows = list(timeline(fit_places, fit_legs, stop_hours, args.gas_miles, gas_hours, windows, combos))
        last = fit_rows[-1]
        kept = {p['code'] for p in fit_places}
        dropped = [p for p in places[1:-1] if p['code'] not in kept]
        drops = ', '.join(f"{p['code']} ({p['points']})" for p in dropped)
        print(f"\nTo fit: drop {drops}. "
              f"About {last.score} points in {last.arrive:.2f} hours, estimated from Google's legs")
        fit_gpx = planRoute.stamped_gpx_name('route-fit', last.score)
        write_gpx(fit_rows, [], args.hours, f"{source}, fitted by dropping stops (estimated)", fit_gpx)
        print(f"Fitted route written to {fit_gpx}; check it with: python checkRoute.py {fit_gpx}"
              + (f" --depart \"{args.depart:%Y-%m-%d %H:%M}\"" if args.depart else ''))


if __name__ == "__main__":
    main()
