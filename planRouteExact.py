#!/usr/bin/env python
"""
Find the provably best rally route from bonus-lat-lon-points.csv using
Google's free OR-Tools CP-SAT solver. Everything runs locally: no Google API
calls and no cost.

It uses the same assumptions as planRoute.py (straight-line miles, average
speed, a stop at each bonus for its picture, start and finish at Rally HQ)
and prints the same table and GPX file, so the two can be compared directly.

Unlike planRoute.py, which finds a good route, this states the problem as
constraints and lets the solver prove no route scores higher. If it runs out
of time first it prints the best route found and how far from the best it
could still be.

    python planRouteExact.py bonus-lat-lon-points.csv --hours 10 --speed 45
"""
import argparse, os, sys, threading, time
from ortools.sat.python import cp_model
import planRoute

# The solver needs whole numbers, so times are in hundredths of a second:
# fine enough that rounding them up for safety only rules out a route that
# fits within a fraction of a second
TICKS_PER_HOUR = 360_000


class Progress(cp_model.CpSolverSolutionCallback):
    """Show the best route found and the most any route could score while
    the solver runs, updated every few seconds."""

    def __init__(self, time_limit):
        super().__init__()
        self.time_limit = time_limit
        self.found = self.bound = None
        self.started = time.monotonic()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.show_every, args=(5,), daemon=True)

    def on_solution_callback(self):
        self.found = int(self.ObjectiveValue())

    def on_bound(self, bound):
        self.bound = int(bound)

    def show(self):
        found = f"best found {self.found} points" if self.found is not None else "no route yet"
        if self.bound is None:
            possible = "working out the most possible"
        else:
            gap = (self.bound - self.found) / self.bound if self.found is not None and self.bound else 0
            possible = f"most possible {self.bound} ({gap:.1%} higher)"
        planRoute.progress(f"Solving: {planRoute.clock(time.monotonic() - self.started)} of "
                           f"{planRoute.clock(self.time_limit)}, {found}, {possible}")

    def show_every(self, seconds):
        while not self.done.wait(seconds):
            self.show()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.done.set()
        self.thread.join()
        self.show()
        print(file=sys.stderr)


def add_bonus_hours(model, candidates, arc_vars, windows, ticks, hundredths, stop, budget, gas, gas_ticks,
                    interval):
    """Time the route, so each bonus with hours is reached while it's open.

    photo[b] is when b's photo is taken, in ticks after the start; it can
    be later than arriving (waiting for b to open), never earlier. Gas stops
    are made on the leg where the odometer passes each interval, as
    planRoute.py times them: odometer[b] is the miles (in hundredths) driven
    to reach b, and gas_before[b] the gas stops made by then.
    """
    photo = {b: model.NewIntVar(*windows.get(b, (0, budget)), f"photo_{b}") for b in candidates}
    if interval:
        odometer = {b: model.NewIntVar(0, 100_000_000, f"odometer_{b}") for b in candidates}
        gas_before = {b: model.NewIntVar(0, 1000, f"gas_before_{b}") for b in candidates}
        for b in candidates:
            # gas_before = floor(odometer / interval)
            model.Add(interval * gas_before[b] <= odometer[b])
            model.Add(interval * gas_before[b] >= odometer[b] - interval + 1)
    else:
        gas_before = dict.fromkeys(candidates, 0)
    for (i, j), x in arc_vars.items():
        if i == 0:
            if interval:
                model.Add(odometer[j] == hundredths[0][j]).OnlyEnforceIf(x)
            model.Add(photo[j] >= ticks[0][j] + gas_ticks * gas_before[j]).OnlyEnforceIf(x)
        elif j == 0:
            # Back at HQ in time, with the rest of the gas stops on the way
            model.Add(photo[i] + stop + ticks[i][0] + gas_ticks * (gas - gas_before[i]) <= budget).OnlyEnforceIf(x)
        else:
            if interval:
                model.Add(odometer[j] == odometer[i] + hundredths[i][j]).OnlyEnforceIf(x)
            model.Add(photo[j] >= photo[i] + stop + ticks[i][j]
                      + gas_ticks * (gas_before[j] - gas_before[i])).OnlyEnforceIf(x)


def solve_exact(planner, time_limit, workers, hint):
    """Return (route, status text, best possible points)."""
    places = planner.places
    budget = int(planner.max_hours * TICKS_PER_HOUR)
    stop = round(planner.stop_hours * TICKS_PER_HOUR)
    # Round driving times up so a route the solver accepts never runs over
    # when checked with exact times
    ticks = [[int(-(-h * TICKS_PER_HOUR // 1)) for h in row] for row in planner.hours]
    # Miles in hundredths, also rounded up, for counting gas stops
    hundredths = [[int(-(-m * 100 // 1)) for m in row] for row in planner.miles]

    # Fastest time between every pair of places, allowing detours through
    # others: with a slow zone, going around it can beat the direct leg, so
    # the limits below use these times to never rule out a possible route
    n = len(places)
    fastest = [row[:] for row in ticks]
    for k in range(n):
        via_k = fastest[k]
        for i in range(n):
            to_k = fastest[i][k]
            row = fastest[i]
            for j in range(n):
                if to_k + via_k[j] < row[j]:
                    row[j] = to_k + via_k[j]

    # Bonus hours in ticks after the start, rounded inward so a route the
    # solver accepts always makes them when checked with exact times
    windows = {}
    if planner.windows is not None:
        for b, window in enumerate(planner.windows):
            if window:
                windows[b] = (max(0, int(-(-window[0] * TICKS_PER_HOUR // 1))),
                              min(budget, int(window[1] * TICKS_PER_HOUR // 1)))

    # Leave out bonuses too far for even a round trip on their own, or that
    # close before you could get there; no route could include them, so this
    # can't change the answer
    candidates = [b for b in range(1, n) if fastest[0][b] + stop + fastest[b][0] <= budget
                  and (b not in windows or max(fastest[0][b], windows[b][0]) <= windows[b][1])]
    nodes = [0] + candidates

    model = cp_model.CpModel()
    visit = {b: model.NewBoolVar(f"visit_{places[b]['code']}") for b in candidates}
    arcs, arc_vars, drive, distance = [], {}, [], []
    for i in nodes:
        for j in nodes:
            if i == j:
                continue
            # Skip legs that couldn't fit even in a route of just these two bonuses
            if (i and j and fastest[0][i] + stop + ticks[i][j] + stop + fastest[j][0] > budget):
                continue
            x = model.NewBoolVar(f"{i}_{j}")
            arc_vars[i, j] = x
            arcs.append((nodes.index(i), nodes.index(j), x))
            drive.append(ticks[i][j] * x)
            distance.append(hundredths[i][j] * x)
    # A bonus that isn't visited loops back on itself, outside the route
    for b in candidates:
        arcs.append((nodes.index(b), nodes.index(b), visit[b].Not()))
    # One loop through HQ and the visited bonuses, each visited at most once
    model.AddCircuit(arcs)
    # --first stops: the route starts with these legs, in this order
    for a, b in zip([0] + planner.lead, planner.lead):
        if (a, b) not in arc_vars:
            sys.exit(f"ERROR: the leg {places[a]['code']} to {places[b]['code']} was left out as too long; "
                     f"try fewer --first stops")
        model.Add(arc_vars[a, b] == 1)
    # Gas stops: at least one for each full gas_miles driven
    # (gas * interval > miles - interval, i.e. gas >= floor(miles / interval))
    gas = model.NewIntVar(0, 1000, 'gas_stops')
    if planner.gas_miles:
        interval = round(planner.gas_miles * 100)
        model.Add(interval * gas >= sum(distance) - interval + 1)
    else:
        model.Add(gas == 0)
    gas_ticks = round(planner.gas_hours * TICKS_PER_HOUR)
    driving = model.NewIntVar(0, budget, 'driving')
    model.Add(driving == sum(drive))
    model.Add(driving + stop * sum(visit.values()) + gas_ticks * gas <= budget)
    # Lower limits on driving that every route meets, which let the solver
    # rule out most routes quickly: a route drives at least the round trip to
    # each bonus it visits, and at least HQ -> a -> b -> HQ (in the quicker
    # order) for each pair. A pair that can't fit together is never both visited.
    for a in candidates:
        model.Add(driving >= (fastest[0][a] + fastest[a][0]) * visit[a])
    for n_a, a in enumerate(candidates):
        for b in candidates[n_a + 1:]:
            pair = min(fastest[0][a] + fastest[a][b] + fastest[b][0], fastest[0][b] + fastest[b][a] + fastest[a][0])
            if pair + 2 * stop > budget:
                model.AddBoolOr([visit[a].Not(), visit[b].Not()])
            elif pair > max(fastest[0][a] + fastest[a][0], fastest[0][b] + fastest[b][0]):
                model.Add(driving >= pair * (visit[a] + visit[b] - 1))
    if planner.windows is not None:
        add_bonus_hours(model, candidates, arc_vars, windows, ticks, hundredths, stop, budget, gas, gas_ticks,
                        round(planner.gas_miles * 100))
    # A combo scores only if every one of its bonuses is visited; one with a
    # bonus no route can reach can't score at all
    combos = []
    for code, points, members in planner.combos:
        if members <= set(candidates):
            got = model.NewBoolVar(f"combo_{code}")
            for b in members:
                model.AddImplication(got, visit[b])
            combos.append((got, points, members))
    model.Maximize(sum(places[b]['points'] * visit[b] for b in candidates)
                   + sum(points * got for got, points, _ in combos))

    # Start the solver from planRoute.py's route, so it begins with a good answer
    for b in candidates:
        model.AddHint(visit[b], b in hint)
    for got, _, members in combos:
        model.AddHint(got, members <= set(hint))
    hint_arcs = set(zip([0] + hint, hint + [0]))
    for (i, j), x in arc_vars.items():
        model.AddHint(x, (i, j) in hint_arcs)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    with Progress(time_limit) as progress:
        solver.best_bound_callback = progress.on_bound
        status = solver.Solve(model, progress)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        sys.exit(f"ERROR: solver found no route ({solver.StatusName(status)})")

    # Follow the chosen legs out of HQ to read off the route
    next_stop = {i: j for (i, j), x in arc_vars.items() if solver.Value(x)}
    route = []
    here = next_stop.get(0, 0)
    while here != 0:
        route.append(here)
        here = next_stop[here]
    bound = int(solver.BestObjectiveBound())
    return route, solver.StatusName(status), bound, solver.WallTime()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('csv_file', nargs='?', default='bonus-lat-lon-points.csv')
    parser.add_argument('--hours', type=float, default=9.5, help='time budget in hours (default 9.5)')
    parser.add_argument('--speed', type=float, default=45, help='average speed in MPH (default 45)')
    parser.add_argument('--stop-minutes', type=float, default=5,
                        help='time spent at each bonus taking its picture (default 5)')
    parser.add_argument('--road-factor', type=float, default=1.0,
                        help='multiply straight-line miles by this to approximate road miles (default 1.0)')
    parser.add_argument('--time-limit', type=float, default=600,
                        help='stop after this many seconds and report the best route so far (default 600)')
    parser.add_argument('--workers', type=int, default=os.cpu_count(),
                        help=f'CPU cores to solve with (default all, {os.cpu_count()} here)')
    parser.add_argument('--gpx',
                        help='also write the route as GPX for Garmin BaseCamp and GPS units '
                             '(default route-exact-DATE-TIME-POINTSpts.gpx)')
    planRoute.add_slow_zone_args(parser)
    planRoute.add_gas_args(parser)
    planRoute.add_first_args(parser)
    planRoute.add_hours_args(parser)
    planRoute.add_combo_args(parser)
    args = parser.parse_args()

    hq, bonuses = planRoute.load_bonuses(args.csv_file)
    slow_zones = planRoute.slow_zones_from_args(args)
    planner = planRoute.Planner(hq, bonuses, args.hours, args.speed, args.stop_minutes, args.road_factor, 0,
                                slow_zones, args.gas_miles, args.gas_minutes, args.start, not args.ignore_hours)
    planRoute.apply_first(planner, args)
    planRoute.apply_combos(planner, args)
    # Start from planRoute.py's full search, so this never reports a worse route
    hint = planner.solve(planRoute.START_WEIGHTS, 6, max(1, args.workers))
    print(f"Solving: starting from a {planner.route_points(hint)}-point route, "
          f"time limit {args.time_limit:g} s ...", file=sys.stderr)

    route, status, bound, seconds = solve_exact(planner, args.time_limit, max(1, args.workers), hint)

    # Check the answer independently of the solver
    if (len(set(route)) != len(route) or planner.route_hours(route) > planner.max_hours + 1e-9
            or route[:len(planner.lead)] != planner.lead):
        sys.exit("ERROR: solver returned an invalid route (repeated bonus, over time or --first stops "
                 "moved); this is a bug")
    # The solver rounds times up to be safe, so a route that fits with a
    # fraction of a second to spare can look too long to it; never report
    # worse than planRoute.py's route
    rounded_out = planner.route_points(hint) > planner.route_points(route)
    if rounded_out:
        route = hint

    points = planner.route_points(route)
    print(f"{len(bonuses)} bonuses, {args.hours} hours at {args.speed} MPH, "
          f"{args.stop_minutes:g} min per stop, road factor {args.road_factor:g}")
    print(f"{planRoute.describe_gas(args)}, {planRoute.describe_slow_zones(slow_zones)}, "
          f"{planRoute.describe_first(planner)}")
    print(f"{planRoute.describe_hours(planner)}")
    print(f"{planRoute.describe_combos(planner)}\n")
    planRoute.print_route(planner, route)
    print()
    if rounded_out:
        print(f"NOT PROVEN: planRoute.py's {points}-point route fits with less than a second to spare, which "
              f"the solver's rounding rules out, so it couldn't check routes that tight. This is that route.")
    elif status == 'OPTIMAL':
        print(f"PROVEN OPTIMAL: no route scores more than {points} points under these assumptions "
              f"(solved in {seconds:.0f} s)")
    else:
        gap = (bound - points) / bound if bound else 0
        print(f"NOT PROVEN: best found {points} points; the best possible is at most {bound} "
              f"({gap:.1%} higher). Stopped at the {args.time_limit:g} s limit; raise --time-limit to keep going")
    gpx = args.gpx or planRoute.stamped_gpx_name('route-exact', points)
    planRoute.write_gpx(planner, route, gpx)
    print(f"\nGPX written to {gpx}")


if __name__ == "__main__":
    main()
