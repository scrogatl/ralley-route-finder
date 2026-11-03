#!/usr/bin/env python
"""
Find where the bonus points are most concentrated.

Each bonus is tried as the center of a circle (--radius miles) and scored by
the points of every bonus inside it. The best circles are then picked one at
a time, each skipping bonuses an earlier one took, so the clusters don't
overlap. For each cluster it estimates the hours to visit all of its bonuses
in a loop (straight-line miles x --road-factor at --speed, plus --stop-minutes
per bonus), giving the points per hour of working that area once you're
there, and how far it is from Rally HQ. Bonus hours and combos are ignored.

    python findClusters.py bonus-lat-lon-points.csv --radius 20 --top 8
"""
import argparse, math
import planRoute
from planRoute import load_bonuses, haversine_miles


def loop_miles(stops):
    """Straight-line miles of a short closed loop through stops: nearest
    neighbour, then 2-opt until no swap of two legs makes it shorter."""
    if len(stops) < 2:
        return 0.0
    tour = [stops[0]]
    rest = stops[1:]
    while rest:
        nearest = min(rest, key=lambda s: haversine_miles(tour[-1], s))
        rest.remove(nearest)
        tour.append(nearest)
    leg = lambda a, b: haversine_miles(tour[a % len(tour)], tour[b % len(tour)])
    improved = True
    while improved:
        improved = False
        for i in range(len(tour) - 1):
            for j in range(i + 2, len(tour) if i else len(tour) - 1):
                if leg(i, j) + leg(i + 1, j + 1) < leg(i, i + 1) + leg(j, j + 1) - 1e-9:
                    tour[i + 1:j + 1] = reversed(tour[i + 1:j + 1])
                    improved = True
    return sum(leg(i, i + 1) for i in range(len(tour)))


def find_clusters(bonuses, radius, top, min_bonuses):
    left = list(bonuses)
    clusters = []
    while left and len(clusters) < top:
        best = None
        for center in left:
            members = [b for b in left if haversine_miles(center, b) <= radius]
            points = sum(b['points'] for b in members)
            if len(members) >= min_bonuses and (best is None or points > best[0]):
                best = (points, center, members)
        if best is None:
            break
        clusters.append(best)
        left = [b for b in left if b not in best[2]]
    return clusters


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('csv_file', nargs='?', default='bonus-lat-lon-points.csv')
    parser.add_argument('--radius', type=float, default=20, help='cluster radius in miles (default 20)')
    parser.add_argument('--top', type=int, default=10, help='how many clusters to list (default 10)')
    parser.add_argument('--min-bonuses', type=int, default=2,
                        help='smallest number of bonuses that counts as a cluster (default 2)')
    parser.add_argument('--speed', type=float, default=planRoute.DEFAULT_SPEED,
                        help=f'average speed in MPH (default {planRoute.DEFAULT_SPEED:g})')
    parser.add_argument('--stop-minutes', type=float, default=5,
                        help='time spent at each bonus taking its picture (default 5)')
    parser.add_argument('--road-factor', type=float, default=planRoute.DEFAULT_ROAD_FACTOR,
                        help='multiply straight-line miles by this to approximate road miles '
                             f'(default {planRoute.DEFAULT_ROAD_FACTOR:g})')
    args = parser.parse_args()

    hq, bonuses = load_bonuses(args.csv_file)
    clusters = find_clusters(bonuses, args.radius, args.top, args.min_bonuses)
    total = sum(b['points'] for b in bonuses)
    print(f"{len(bonuses)} bonuses, {total:,} points; clusters within {args.radius:g} miles of a bonus, "
          f"{args.speed:g} MPH, {args.stop_minutes:g} min per stop, road factor {args.road_factor:g}\n")
    print(f"{'#':>2}  {'Center':<6} {'Bonuses':>7} {'Points':>7} {'Share':>6} {'Loop mi':>7} {'Hours':>5} "
          f"{'Pts/h':>6} {'HQ mi':>6}  Members, highest points first")
    for n, (points, center, members) in enumerate(clusters, 1):
        miles = loop_miles(sorted(members, key=lambda b: b['code'])) * args.road_factor
        hours = miles / args.speed + len(members) * args.stop_minutes / 60
        members = sorted(members, key=lambda b: -b['points'])
        print(f"{n:>2}  {center['code']:<6} {len(members):>7} {points:>7,} {points / total:>6.0%} {miles:>7.0f} "
              f"{hours:>5.1f} {points / hours:>6,.0f} {haversine_miles(hq, center) * args.road_factor:>6.0f}  "
              + ','.join(b['code'] for b in members))
    print("\nLoop mi and Hours: a loop through the cluster's bonuses, not counting getting there. "
          "HQ mi: from Rally HQ to the center bonus.\nMembers can be pasted into the web app's Must visit box "
          "or given to planRoute.py --must.")


if __name__ == "__main__":
    main()
