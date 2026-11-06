#!/usr/bin/env python
"""
Plan a rally route by classic tree search, with tunable heuristic cut-offs.

Where planRoute.py improves whole routes (insert, drop, swap) and
planRouteExact.py hands the problem to a constraint solver, this builds
routes the way a textbook AI search does: a route is a path from Rally HQ,
one stop at a time, and every partial route is a node in a tree whose
children add one more bonus that still leaves time to get back. Each node is
judged by f = g + H_WEIGHT x h, where g is the points so far (with any combo
it completes) and h is the most points the rest of the day could add: the
bonuses still reachable, best points per hour first, packed into the time
left as if each cost only its stop plus the quickest drive into it (a
"fractional knapsack"). A combo's points are shared among the stops it still
needs. h is never too low, so a branch whose f (with H_WEIGHT 1) is no more
than a route already found can't hold a better one.

Two search methods:

  beam  Breadth-first, one stop at a time, keeping only the BEAM_WIDTH best
        nodes at each depth by f, at most DIVERSITY of them ending at the
        same bonus. Of routes with the same stops ending at the same bonus,
        only the quickest is kept. Wider beams look at more routes and run
        longer; --widen keeps doubling the width until --time-limit.
        Expanding the beam is spread across all CPU cores.
  dfs   Depth-first branch and bound: follow the most promising child first,
        and skip any node whose f can't beat the best complete route so far
        (it starts from a beam search's best route, so it can skip from the
        start). H_WEIGHT below 1 prunes harder, so it's faster but may miss
        the best route. With --branch 0 and H_WEIGHT 1 nothing is cut off
        that could do better, so if it finishes before --time-limit, no
        route scores more: it proves days up to about 6 hours this way.

Both look at only the BRANCH best children of each node, by points per hour
of getting there, the main cut-off: lower is faster and greedier. The
settings, bonus hours, gas stops, slow zones, combos, --first and --must are
the same as planRoute.py's, and so are the printout and GPX; front-loading
isn't supported, but the route is ordered to bank points early. --polish
runs planRoute.py's drop-and-reinsert search on the result.

    python planRouteSearch.py                       # beam, width 2000, branch 12
    python planRouteSearch.py --widen --time-limit 120
    python planRouteSearch.py --method dfs --branch 0 --hours 6
"""
import argparse, collections, multiprocessing, os, signal, sys, time
import planRoute
from planRoute import Planner, load_bonuses, clock

# A partial route from Rally HQ. elapsed is the hours after leaving its last
# stop, miles the distance so far, points its score (bonuses plus combos it
# completes), stops the set of bonuses visited
Node = collections.namedtuple('Node', 'route last elapsed miles points stops')

# Beam search's default weight on h. Lower ranks partial routes more by the
# points they already have; this did best on the 2026 bonuses
BEAM_H_WEIGHT = 0.4
# planRoute.py --quick and the web app's quick mode: the beam search that did
# best on the 2026 bonuses, then planRoute.py's drop-and-reinsert search
QUICK_WIDTH, QUICK_BRANCH = 2000, 12

# Depth-first search remembers this many (last stop, stops) states for
# dominance pruning, then starts over, to bound its memory
SEEN_LIMIT = 2_000_000


class TreeSearch:
    def __init__(self, planner, branch, h_weight, diversity=0):
        self.p = planner
        self.branch = branch
        self.h_weight = h_weight
        self.diversity = diversity
        # A multiprocessing pool to expand beam search nodes on, set by main
        self.pool, self.workers = None, 1
        n = len(planner.places)
        self.bonuses = range(1, n)
        # Every other place in order of how quickly you can drive from it to
        # each bonus, for the bound
        self.nearest = [None] + [sorted((planner.hours[a][b], a) for a in range(n) if a != b)
                                 for b in range(1, n)]
        # Combos each bonus belongs to
        self.combos_of = collections.defaultdict(list)
        for _, combo_points, members in planner.combos:
            for b in members:
                self.combos_of[b].append((combo_points, members))
        self.nodes = 0

    def gas(self, miles, leg_miles):
        """Gas stops on a leg of leg_miles starting with miles on the odometer."""
        gas_miles = self.p.gas_miles
        return int((miles + leg_miles) // gas_miles) - int(miles // gas_miles) if gas_miles else 0

    def start(self):
        node = Node((), 0, 0.0, 0.0, 0, frozenset())
        for b in self.p.lead:
            node = self.extend(node, b)
            if node is None:
                sys.exit("ERROR: --first stops don't fit in the time budget and their hours")
        return node

    def extend(self, node, b):
        """The node with b added, timed as Planner.timed_hours does, or None
        if b is closed by then or there's no time left to get back to HQ."""
        p = self.p
        leg_miles = p.miles[node.last][b]
        elapsed = node.elapsed + p.hours[node.last][b] + p.gas_hours * self.gas(node.miles, leg_miles)
        miles = node.miles + leg_miles
        if p.windows is not None and p.windows[b]:
            opens, closes = p.windows[b]
            if elapsed > closes:
                return None
            elapsed = max(elapsed, opens)
        elapsed += p.stop_hours
        if elapsed + p.hours[b][0] + p.gas_hours * self.gas(miles, p.miles[b][0]) > p.max_hours:
            return None
        stops = node.stops | {b}
        points = node.points + p.points[b] + sum(combo_points for combo_points, members in self.combos_of[b]
                                                 if members <= stops)
        return Node(node.route + (b,), b, elapsed, miles, points, stops)

    def reachable(self, node, b):
        """Could b still be added after node, ignoring every other stop and
        gas? Optimistic, so never wrongly False."""
        p = self.p
        arrive = node.elapsed + p.hours[node.last][b]
        if p.windows is not None and p.windows[b]:
            if arrive > p.windows[b][1]:
                return False
            arrive = max(arrive, p.windows[b][0])
        return arrive + p.stop_hours + p.hours[b][0] <= p.max_hours

    def values(self, node):
        """{bonus: points} for each unvisited bonus still reachable after
        node, each with an equal share of every combo it could still help
        complete. Any set of stops scores at most the sum of their values,
        since a combo's points are split among the stops it still needs."""
        stops = node.stops
        values = {b: self.p.points[b] for b in self.bonuses if b not in stops and self.reachable(node, b)}
        for _, combo_points, members in self.p.combos:
            missing = members - stops
            if missing and all(b in values for b in missing):
                for b in missing:
                    values[b] += combo_points / len(missing)
        return values

    def bound(self, node):
        """h: the most points the time left could still add. The reachable
        bonuses are packed best points per hour first, each costing its stop
        plus the quickest drive into it from a place the route could still
        come from (the last stop or another unvisited bonus), the last one in
        part (a "fractional knapsack"). The time left is less the shortest
        drive home from any of them. It ignores gas and waits, so it is never
        too low."""
        values = self.values(node)
        if not values:
            return 0.0
        p, stops, last = self.p, node.stops, node.last
        cost = {}
        for b in values:
            for hours, a in self.nearest[b]:
                if a == last or (a and a not in stops):
                    break
            cost[b] = p.stop_hours + hours
        left = p.max_hours - node.elapsed - min(p.hours[b][0] for b in values)
        total = 0.0
        for b in sorted(values, key=lambda b: (-values[b] / cost[b], b)):
            if cost[b] <= left:
                total += values[b]
                left -= cost[b]
            else:
                total += values[b] * max(left, 0.0) / cost[b]
                break
        return total

    def score(self, node, h_weight=None):
        """f = g + H_WEIGHT x h."""
        return node.points + (self.h_weight if h_weight is None else h_weight) * self.bound(node)

    def complete(self, node):
        """True if node can end the route: it has every --must stop."""
        return self.p.required <= node.stops

    def hopeless(self, node):
        """True if some --must stop not yet visited can't be reached any more."""
        return any(b not in node.stops and not self.reachable(node, b) for b in self.p.required)

    def children(self, node):
        """The BRANCH best next stops, by points per hour it takes to get
        there and take the picture. A combo stop counts its share of the combo
        (see values), so the search heads for combos before the last stop."""
        values = self.values(node)
        options = []
        for b in values:
            child = self.extend(node, b)
            if child is None or self.hopeless(child):
                continue
            # --must stops always count as worth going to
            gain = values[b] + (1e6 if b in self.p.required else 0)
            options.append((-gain / (child.elapsed - node.elapsed), b, child))
        self.nodes += len(options)
        options.sort()
        return [child for _, _, child in options[:self.branch or None]]

    def better(self, a, b):
        """True if complete node a beats b: more points, then less time."""
        return b is None or a.points > b.points or (a.points == b.points and a.elapsed < b.elapsed - 1e-9)

    def dominated(self, node, seen):
        """True if seen has a route with the same stops ending at the same
        bonus that is no farther, and no later leaving it once the gas stops
        already made are taken out (it may still have one of those to make),
        so node can't do better. Otherwise remember node if it's the
        quickest such route yet."""
        key = (node.last, node.stops)
        other = seen.get(key)
        hours = node.elapsed - self.p.gas_hours * self.p.gas_stops(node.miles)
        if other is not None and other[0] <= hours and other[1] <= node.miles:
            return True
        if other is None or hours < other[0]:
            if len(seen) >= SEEN_LIMIT:
                # Forgetting only means some repeats get searched again
                seen.clear()
            seen[key] = (hours, node.miles)
        return False

    def expand(self, node, h_weight=None):
        """(how many children node has, [(f, last stop)] for the BRANCH
        best). Only the stop comes back, since sending whole routes between
        processes costs more than the caller rebuilding them with extend."""
        before = self.nodes
        children = self.children(node)
        # The caller adds up the counts, since a worker's can't reach it
        made, self.nodes = self.nodes - before, before
        return made, [(self.score(child, h_weight), child.last) for child in children]

    def beam(self, width, h_weight=None):
        """Breadth-first, keeping the width best routes at each depth by
        f, with h_weight in place of H_WEIGHT if given. Returns the best
        complete route seen."""
        started = time.monotonic()
        frontier = [self.start()]
        best = frontier[0] if self.complete(frontier[0]) else None
        depth = 0
        while frontier:
            depth += 1
            # Expand and score every route in the frontier, on all the
            # workers if there are several. Results come back in frontier
            # order, so the route found doesn't depend on how many there are
            tasks = [(node, h_weight) for node in frontier]
            if self.pool:
                expanded = self.pool.map(_expand, tasks, chunksize=max(1, len(tasks) // (4 * self.workers)))
            else:
                expanded = [self.expand(*task) for task in tasks]
            # Of the routes with the same stops ending at the same bonus,
            # keep the quickest: the order of the others doesn't matter
            kept = {}
            for node, (made, children) in zip(frontier, expanded):
                self.nodes += made
                for f, b in children:
                    child = self.extend(node, b)
                    if self.complete(child) and self.better(child, best):
                        best = child
                    key = (child.last, child.stops)
                    other = kept.get(key)
                    if other is None or (child.elapsed, child.miles) < (other[1].elapsed, other[1].miles):
                        kept[key] = (f, child)
            # Best f first, ties to the route that sorts first, so the result
            # doesn't depend on the order children were made
            scored = sorted((-f, c.route, c) for f, c in kept.values())
            if self.diversity:
                # So the beam doesn't fill up with variations on one route
                ending = collections.Counter()
                frontier = []
                for _, _, c in scored:
                    if ending[c.last] < self.diversity:
                        ending[c.last] += 1
                        frontier.append(c)
                        if len(frontier) == width:
                            break
            else:
                frontier = [c for _, _, c in scored[:width]]
            planRoute.progress(f"Beam search: depth {depth}, {len(kept):,} routes, kept {len(frontier):,}, "
                     f"best so far {best.points if best else 0} points, {clock(time.monotonic() - started)} elapsed")
        print(file=sys.stderr)
        self.last_seconds = time.monotonic() - started
        return best

    def widen(self, width, time_limit):
        """Beam searches of width, 2 x width, 4 x width and so on (and the
        same for diversity), until the next would run past time_limit; the
        best route of any, and the last width."""
        started = time.monotonic()
        best = None
        while True:
            node = self.beam(width)
            if node is not None and self.better(node, best):
                best = node
            spent = time.monotonic() - started
            planRoute.progress(f"Width {width:,} done: best so far {best.points if best else 0} points, "
                     f"{clock(spent)} elapsed\n")
            # The next pass takes about twice as long as this one
            if spent + 2 * self.last_seconds > time_limit:
                return best, width
            width *= 2
            # Keep the same share of the beam for routes ending at each bonus
            self.diversity *= 2

    def dfs(self, time_limit, best=None):
        """Depth-first branch and bound from best (a complete node, or None),
        until it has tried every branch or time_limit seconds pass. Returns
        the best route and whether it finished."""
        started = time.monotonic()
        root = self.start()
        if self.complete(root) and self.better(root, best):
            best = root
        best = [best]
        seen = {}
        visits = [0]
        stopped = [False]

        def visit(node):
            visits[0] += 1
            if visits[0] % 1000 == 0:
                elapsed = time.monotonic() - started
                stopped[0] = elapsed > time_limit
                planRoute.progress(f"Depth-first: {self.nodes:,} nodes, best so far "
                         f"{best[0].points if best[0] else 0} points, {clock(elapsed)} elapsed")
            for child in self.children(node):
                if stopped[0]:
                    return
                if self.complete(child) and self.better(child, best[0]):
                    best[0] = child
                if self.dominated(child, seen):
                    continue
                # Cut off any branch that can't beat the best route so far
                if best[0] is not None and self.score(child) <= best[0].points:
                    continue
                visit(child)

        visit(root)
        print(file=sys.stderr)
        return best[0], not stopped[0]


# Each worker process gets its own copy of the search once, as in planRoute.py
_worker_search = None


def quick_route(planner, workers):
    """A route by beam search with the defaults (width 2000, branch 12),
    polished with planRoute.py's drop-and-reinsert search and ordered to bank
    points early: about 4x faster than Planner.solve, and as good on the 2026
    bonuses, but it may miss a better route on other data."""
    if planner.only:
        return planner.only_route()
    # Stops with planRoute.py's explanation if the --must stops can't fit
    planner.must_route()
    search = TreeSearch(planner, QUICK_BRANCH, BEAM_H_WEIGHT, QUICK_WIDTH // 10)
    if workers > 1:
        search.pool = multiprocessing.Pool(workers, initializer=_init_worker, initargs=(search,))
        search.workers = workers
    try:
        best = search.beam(QUICK_WIDTH)
    finally:
        # Its work is done, or it's being stopped: either way end the workers now
        if search.pool:
            search.pool.terminate()
    if best is None:
        sys.exit("ERROR: found no route with every --must stop")
    planRoute.progress(f"Polishing the beam search's {best.points}-point route")
    route = planner.local_search(planner.improve(list(best.route)), 1.0, 6)
    route = planner.front_load_order(route)
    planRoute.progress(f"Search done: {planner.route_points(route)} points")
    print(file=sys.stderr)
    if (len(set(route)) != len(route) or planner.route_hours(route) > planner.max_hours + 1e-9
            or route[:len(planner.lead)] != planner.lead or not planner.required <= set(route)):
        sys.exit("ERROR: search produced an invalid route; this is a bug")
    return route


def _init_worker(search):
    global _worker_search
    _worker_search = search
    # As planRoute.py's workers: exit when the pool is shut down early
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def _expand(task):
    return _worker_search.expand(*task)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('csv_file', nargs='?', default='bonus-lat-lon-points.csv')
    parser.add_argument('--method', choices=('beam', 'dfs'), default='beam', help='search method (default beam)')
    parser.add_argument('--beam-width', type=int, default=2000,
                        help='beam: partial routes kept at each depth; dfs: width of the beam search whose route '
                             'it starts from, 0 to start from nothing (default 2000)')
    parser.add_argument('--branch', type=int, default=12,
                        help='next stops tried from each partial route, best points per hour first; 0 for all '
                             '(default 12)')
    parser.add_argument('--h-weight', type=float,
                        help='weight of the estimate of points still to come (default 0.4 for beam, 1 for dfs; '
                             'dfs below 1 prunes harder and may miss the best route)')
    parser.add_argument('--diversity', type=int,
                        help='beam: keep at most this many routes ending at the same bonus at each depth; '
                             '0 for no limit (default a tenth of the beam width)')
    parser.add_argument('--widen', action='store_true',
                        help='beam: run again at twice the width, and again, until --time-limit')
    parser.add_argument('--time-limit', type=float, default=60,
                        help='dfs, and beam with --widen: stop after about this many seconds with the best route '
                             'found (default 60)')
    parser.add_argument('--workers', type=int, default=os.cpu_count(),
                        help=f'beam: CPU cores to expand routes on (default all, {os.cpu_count()} here)')
    parser.add_argument('--polish', action='store_true',
                        help="then improve the result with planRoute.py's drop-and-reinsert search")
    parser.add_argument('--hours', type=float, default=planRoute.DEFAULT_HOURS,
                        help=f'time budget in hours (default {planRoute.DEFAULT_HOURS:g})')
    parser.add_argument('--speed', type=float, default=planRoute.DEFAULT_SPEED,
                        help=f'average speed in MPH (default {planRoute.DEFAULT_SPEED:g})')
    parser.add_argument('--stop-minutes', type=float, default=5,
                        help='minutes stopped at each bonus: parking, finding the sign, the photo and getting going again '
                             '(default 5)')
    parser.add_argument('--road-factor', type=float, default=planRoute.DEFAULT_ROAD_FACTOR,
                        help='multiply straight-line miles by this to approximate road miles '
                             f'(default {planRoute.DEFAULT_ROAD_FACTOR:g})')
    parser.add_argument('--gpx',
                        help='also write the route as GPX for Garmin BaseCamp and GPS units '
                             '(default route-search-DATE-TIME-POINTSpts.gpx)')
    planRoute.add_leg_args(parser)
    planRoute.add_slow_zone_args(parser)
    planRoute.add_gas_args(parser)
    planRoute.add_first_args(parser)
    planRoute.add_hours_args(parser)
    planRoute.add_combo_args(parser)
    args = parser.parse_args()

    hq, bonuses = load_bonuses(args.csv_file)
    bonuses = planRoute.planned_bonuses(bonuses, args)
    slow_zones = planRoute.slow_zones_from_args(args)
    planner = Planner(hq, bonuses, args.hours, args.speed, args.stop_minutes, args.road_factor, 0,
                      slow_zones, args.gas_miles, args.gas_minutes, args.start, not args.ignore_hours,
                      **planRoute.timing_options(args))
    planRoute.apply_first(planner, args)
    planRoute.apply_combos(planner, args)
    if args.h_weight is None:
        args.h_weight = BEAM_H_WEIGHT if args.method == 'beam' else 1.0
    if args.diversity is None:
        args.diversity = args.beam_width // 10
    search = TreeSearch(planner, args.branch, args.h_weight, args.diversity)
    started = time.monotonic()
    if args.workers > 1 and args.beam_width:
        search.pool = multiprocessing.Pool(args.workers, initializer=_init_worker, initargs=(search,))
        search.workers = args.workers
    if args.method == 'beam' and args.widen:
        best, width = search.widen(args.beam_width, args.time_limit)
        how = f"beam search, widened from {args.beam_width:,} to {width:,}"
    elif args.method == 'beam':
        best = search.beam(args.beam_width)
        how = f"beam search, width {args.beam_width:,}"
    else:
        seed = search.beam(args.beam_width, BEAM_H_WEIGHT) if args.beam_width else None
        best, finished = search.dfs(args.time_limit, seed)
        how = (f"depth-first branch and bound from a width {args.beam_width:,} beam's {seed.points} points, "
               if seed else "depth-first branch and bound, ")
        how += "searched every branch it kept" if finished else f"stopped at the {args.time_limit:g} s limit"
        if finished and not args.branch and args.h_weight >= 1:
            how += ": no route scores more"
    if search.pool:
        search.pool.close()
    if best is None:
        sys.exit("ERROR: found no route with every --must stop")
    seconds = time.monotonic() - started
    route = list(best.route)
    found = planner.route_points(route)
    if found != best.points:
        sys.exit(f"ERROR: search scored its route {best.points} points, but it's {found}; this is a bug")
    if args.polish:
        planRoute.progress("Polishing with planRoute.py's drop-and-reinsert search")
        route = planner.local_search(planner.improve(route), 1.0, 6)
        print(file=sys.stderr)
    polish_seconds = time.monotonic() - started - seconds
    # Same stops, reordered to bank points early where the hours allow
    route = planner.front_load_order(route)
    if (len(set(route)) != len(route) or planner.route_hours(route) > planner.max_hours + 1e-9
            or route[:len(planner.lead)] != planner.lead or not planner.required <= set(route)):
        sys.exit("ERROR: search produced an invalid route; this is a bug")

    print(f"{len(bonuses)} bonuses, {args.hours} hours at {args.speed} MPH, "
          f"{args.stop_minutes:g} min per stop, {args.leg_minutes:g} per leg, {planRoute.describe_roads(planner, args.road_factor)}")
    print(f"{planRoute.describe_gas(args)}, {planRoute.describe_slow_zones(slow_zones)}, "
          f"{planRoute.describe_first(planner)}")
    print(f"{planRoute.describe_hours(planner)}")
    print(f"{planRoute.describe_combos(planner)}")
    print(f"{how}, branch {args.branch or 'all'}, h-weight {args.h_weight:g}"
          + (f", diversity {search.diversity}" if args.method == 'beam' and search.diversity else "")
          + f": {found} points, "
          f"{search.nodes:,} nodes in {clock(seconds)}"
          + (f"; polished to {planner.route_points(route)} in {clock(polish_seconds)}" if args.polish else "")
          + "\n")
    planRoute.print_route(planner, route)
    gpx = args.gpx or planRoute.stamped_gpx_name('route-search', planner.route_points(route))
    planRoute.write_gpx(planner, route, gpx)
    print(f"\nGPX written to {gpx}")


if __name__ == "__main__":
    main()
