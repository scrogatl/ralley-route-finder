#!/usr/bin/env python
"""
Build a table of road miles between every pair of places in the bonus file
(Rally HQ included), from a GraphHopper server, for planRoute.py
--road-miles (and the web app's Road miles switch).

GraphHopper is a free routing server that runs locally on OpenStreetMap data,
e.g. route-camp's (http://localhost:8989, Georgia, profile "car"). Nothing is
billed. Its server has no matrix endpoint, so this asks for one route per
pair: about 18,000 for 135 places, a minute or two with several workers.

The table has a row per pair, both ways: the two codes, their coordinates,
the road miles, and GraphHopper's drive minutes (for reference; the planner
times legs from the miles with --speed, slow zones and --leg-minutes, which
matched Google better than GraphHopper's own times). The planner looks pairs
up by coordinates, so a bonus that has moved since the table was built gets
the straight-line estimate instead, with a warning.

    python buildRoadMiles.py bonus-lat-lon-points.csv
"""
import argparse, concurrent.futures, csv, json, os, sys, time, urllib.error, urllib.request

import planRoute

DEFAULT_URL = 'http://localhost:8989'


def road_leg(url, profile, a, b):
    """(miles, minutes) by road from a to b, or None if GraphHopper finds no route."""
    body = json.dumps({'points': [[a['lon'], a['lat']], [b['lon'], b['lat']]], 'profile': profile,
                       'calc_points': False, 'instructions': False}).encode()
    request = urllib.request.Request(url.rstrip('/') + '/route', body, {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            path = json.load(response)['paths'][0]
    except urllib.error.HTTPError as error:
        if error.code == 400:
            # e.g. a point too far from any road
            return None
        raise
    return path['distance'] / planRoute.METERS_PER_MILE, path['time'] / 60000


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('csv_file', nargs='?', default='bonus-lat-lon-points.csv')
    parser.add_argument('--out', help=f'the table to write (default {planRoute.ROAD_MILES_CSV} next to the bonus file)')
    parser.add_argument('--graphhopper', default=DEFAULT_URL, help=f'GraphHopper server (default {DEFAULT_URL})')
    parser.add_argument('--profile', default='car', help='GraphHopper profile (default car)')
    parser.add_argument('--workers', type=int, default=8, help='requests at once (default 8)')
    args = parser.parse_args()
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.csv_file)), planRoute.ROAD_MILES_CSV)

    hq, bonuses = planRoute.load_bonuses(args.csv_file)
    places = [hq] + bonuses
    pairs = [(a, b) for a in places for b in places if a is not b]
    try:
        road_leg(args.graphhopper, args.profile, places[0], places[1])
    except (urllib.error.URLError, OSError) as error:
        sys.exit(f"ERROR: can't reach GraphHopper at {args.graphhopper}: {error}")
    print(f"{len(places)} places, {len(pairs)} routes from {args.graphhopper} ({args.profile})")

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        legs = list(pool.map(lambda pair: road_leg(args.graphhopper, args.profile, *pair), pairs))
    missing = [f"{a['code']}-{b['code']}" for (a, b), leg in zip(pairs, legs) if leg is None]

    with open(out, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['from', 'to', 'from_lat', 'from_lon', 'to_lat', 'to_lon', 'miles', 'minutes'])
        for (a, b), leg in zip(pairs, legs):
            if leg is not None:
                writer.writerow([a['code'], b['code'], a['lat'], a['lon'], b['lat'], b['lon'],
                                 f"{leg[0]:.3f}", f"{leg[1]:.2f}"])
    print(f"Wrote {len(pairs) - len(missing)} legs to {out} in {time.monotonic() - started:.0f} s")
    if missing:
        print(f"WARNING: no road route for {len(missing)} legs (planned as straight lines): "
              + ", ".join(missing[:20]) + (" ..." if len(missing) > 20 else ""))


if __name__ == '__main__':
    main()
