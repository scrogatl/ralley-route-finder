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
they open, and reported as missed if reached after they close.

Without --depart, the whole route goes in one request per 25 stops and the
times have no traffic. With --depart, each leg is its own request, leaving
when you'd leave that stop, and the times include Google's traffic forecast.

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


def leg_result(leg):
    """Road miles and driving hours for one leg of a Routes response. With
    traffic on, the duration includes Google's traffic forecast."""
    return leg.get('distanceMeters', 0) / METERS_PER_MILE, float(leg['duration'].rstrip('s')) / 3600


def directions(api_key, places, depart=None):
    """Ask the Routes API for the driving route through places in order;
    with depart (a datetime), use the traffic forecast for that time."""
    body = {'origin': waypoint(places[0]), 'destination': waypoint(places[-1]),
            'intermediates': [waypoint(p) for p in places[1:-1]], 'travelMode': 'DRIVE'}
    if depart:
        body['routingPreference'] = 'TRAFFIC_AWARE'
        body['departureTime'] = depart.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    else:
        body['routingPreference'] = 'TRAFFIC_UNAWARE'
    response = requests.post(ROUTES_URL, json=body, timeout=60,
                             headers={'X-Goog-Api-Key': api_key, 'X-Goog-FieldMask': FIELD_MASK})
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


def fetch_batched(api_key, places):
    """One request per 25 stops; no traffic. Returns ([(miles, hours)] per leg, [polyline])."""
    legs, polylines = [], []
    start = 0
    while start < len(places) - 1:
        # Each request ends where the next one starts
        end = min(start + MAX_WAYPOINTS + 1, len(places) - 1)
        route = directions(api_key, places[start:end + 1])
        legs += [leg_result(leg) for leg in route['legs']]
        polylines.append(route['polyline']['encodedPolyline'])
        start = end
    return legs, polylines


def fetch_with_traffic(api_key, places, depart, stop_hours, gas_miles, gas_hours, windows):
    """One request per leg, leaving when you'd leave that stop, so each leg
    gets the traffic forecast for its time of day."""
    legs, polylines = [], []
    elapsed = miles = 0
    for n, (a, b) in enumerate(zip(places, places[1:])):
        print(f"\rAsking Google: leg {n + 1} of {len(places) - 1}", end='', file=sys.stderr, flush=True)
        route = directions(api_key, [a, b], depart + timedelta(hours=elapsed))
        leg_miles, leg_hours = leg_result(route['legs'][0])
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


Row = collections.namedtuple('Row', 'place leg_miles miles leg_hours arrive wait leave score gas missed')


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


def timeline(places, legs, stop_hours, gas_miles, gas_hours, windows):
    """Yield a Row for HQ, each stop, then HQ. A bonus reached before it opens
    is waited for; one reached after it closes is missed and scores nothing."""
    miles = hours = score = 0
    yield Row(places[0], 0, 0, 0, 0, 0, 0, 0, 0, False)
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
        if not missed:
            score += place['points']
        yield Row(place, leg_miles, miles, leg_hours, arrive, wait, hours, score, gas, missed)


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
    planRoute.add_gas_args(parser)
    args = parser.parse_args()

    args.gpx_file = args.gpx_file or newest_route()
    places = load_route(args.gpx_file)
    stop_hours, gas_hours = args.stop_minutes / 60, args.gas_minutes / 60
    start = f"{args.depart:%H:%M}" if args.depart else args.start
    windows = bonus_windows(args.bonuses, start)
    if args.depart and args.depart.timestamp() < datetime.now().timestamp():
        sys.exit("ERROR: --depart is in the past; Google only forecasts traffic for future times")
    api_key = os.environ.get('GMAPS_API_KEY') or sys.exit("ERROR: set GMAPS_API_KEY to your Google Maps API key")
    if args.depart:
        legs, polylines = fetch_with_traffic(api_key, places, args.depart, stop_hours, args.gas_miles, gas_hours,
                                             windows)
        source = f"Google, with traffic, leaving {args.depart:%a %b %d %H:%M}"
    else:
        legs, polylines = fetch_batched(api_key, places)
        source = "Google, no traffic"
    rows = list(timeline(places, legs, stop_hours, args.gas_miles, gas_hours, windows))
    begin = planRoute.clock_hours(start)

    def time_of_day(hours):
        minutes = round((begin + hours) * 60)
        return f"{minutes // 60 % 24}:{minutes % 60:02}"

    print(f"{args.gpx_file}: {len(places) - 2} bonuses, {source}")
    print(f"{args.stop_minutes:g} min per stop, {planRoute.describe_gas(args)}, start {start}, "
          + (f"bonus hours from {args.bonuses}" if windows else "no bonus hours") + "\n")
    print(f"{'#':>3}  {'Bonus':<24} {'State':<5} {'Points':>6} {'Line mi':>7} {'Road mi':>7} {'Total mi':>8} {'Drive':>6} "
          f"{'Arrive':>6} {'Leave':>6} {'Time':>6} {'Score':>6}")
    line_miles = 0
    for n, row in enumerate(rows):
        place = row.place
        straight = planRoute.haversine_miles(rows[n - 1].place, place) if n else 0
        line_miles += straight
        notes = []
        if row.gas:
            notes.append(f"+ {row.gas} gas stop{'s' if row.gas > 1 else ''} on the way")
        window = windows.get(place['code'])
        if row.missed:
            notes.append(f"MISSED: closes {window[3]}")
        elif row.wait:
            notes.append(f"waits {row.wait * 60:.0f} min to open at {window[2]}")
        elif window:
            notes.append(f"open {window[2]}-{window[3]}")
        print(f"{n:>3}  {place['code']:<24} {place['state']:<5} {place['points']:>6} {straight:>7.1f} "
              f"{row.leg_miles:>7.1f} {row.miles:>8.1f} {row.leg_hours * 60:>4.0f} m {row.arrive:>6.2f} "
              f"{row.leave:>6.2f} {time_of_day(row.arrive):>6} {row.score:>6}{'  ' + '; '.join(notes) if notes else ''}")

    last = rows[-1]
    miles, hours, points = last.miles, last.arrive, last.score
    drive_hours = sum(h for _, h in legs)
    print()
    print(f"Bonuses: {len(places) - 2}   Points: {points}   Road miles: {miles:.0f}   "
          f"Gas stops: {gas_stops(miles, args.gas_miles)}   Hours: {hours:.2f} of {args.hours}")
    missed = [row for row in rows if row.missed]
    if missed:
        lost = sum(row.place['points'] for row in missed)
        print(f"MISSED HOURS: " + ", ".join(f"{row.place['code']} (arrive {time_of_day(row.arrive)}, "
                                             f"closes {windows[row.place['code']][3]})" for row in missed)
              + f"; {lost} points not counted")
    if hours <= args.hours:
        print(f"FITS: back at Rally HQ with {(args.hours - hours) * 60:.0f} minutes to spare")
    else:
        late = [row.place['code'] for row in rows[1:-1] if row.leave > args.hours]
        print(f"OVER by {(hours - args.hours) * 60:.0f} minutes. Stops you'd leave after time runs out: "
              f"{', '.join(late) or 'none (only the drive back is late)'}")
    if line_miles and drive_hours:
        print(f"To plan closer to these roads: planRoute.py --road-factor {miles / line_miles:.2f} "
              f"--speed {miles / drive_hours:.0f}")
    gpx = args.gpx or planRoute.stamped_gpx_name('route-google', points)
    write_gpx(rows, polylines, args.hours, source, gpx)
    print(f"\nGPX written to {gpx}")


if __name__ == "__main__":
    main()
