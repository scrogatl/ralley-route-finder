"""
A small password-protected web app for running planRoute.py scenarios.

People fill in a form with the planner's settings, the run goes in a queue
(one at a time, since each run uses every CPU core), and the result page
shows the route table, a map and a GPX download. Every run is saved, so the
home page lists them all to compare, and the same settings on the same data
return the saved result instantly. Planning never calls Google; with
GOOGLE_CHECK on, a finished route can be checked on real roads with the
Google Maps Routes API, as checkRoute.py does.

Environment:
    APP_PASSWORD     required; the password for the whole site, asked for on a
                     login page; changing it logs everyone out
    DATA_DIR         folder with bonus-lat-lon-points.csv and bonus-combos.csv
                     from extractDatafromGPX.py (default: the repo folder)
    RESULTS_DIR      where runs are saved (default: DATA_DIR/web-scenarios)
    PLANNER_WORKERS  CPU cores per run (default: all)
    GOOGLE_CHECK     'on' adds a "Check with Google" button to finished routes;
                     leave it off on a public site, since every check is billed
                     to your Google account (default: off)
    GMAPS_API_KEY    the Google Maps API key, needed when GOOGLE_CHECK is on
    RALLY_TZ         time zone for Google departure times (default America/New_York)
    NEW_RELIC_LICENSE_KEY  turns on New Relic APM (requests, planner runs as
                     background tasks, Google calls) and Browser monitoring
                     on every page (default: off)
    NEW_RELIC_APP_NAME     the app's name in New Relic (default Rally Route Finder)

    APP_PASSWORD=secret flask --app webapp/app.py run    # to try it locally
"""
import argparse, glob, hashlib, hmac, json, math, os, queue, re, shutil, sys, threading, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# New Relic, only with a license key. It starts before Flask is imported, so
# it can instrument it; the rest of its settings can come from NEW_RELIC_*
# environment variables
NEW_RELIC = bool(os.environ.get('NEW_RELIC_LICENSE_KEY'))
if NEW_RELIC:
    # Before the import, which is when the agent reads its settings
    os.environ.setdefault('NEW_RELIC_APP_NAME', 'Rally Route Finder')
    import newrelic.agent
    newrelic.agent.initialize()

from flask import Flask, Response, abort, redirect, render_template, request, send_file, session, url_for

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import planRoute, planRouteSearch

PASSWORD = os.environ.get('APP_PASSWORD') or sys.exit("ERROR: set APP_PASSWORD to the site's password")
DATA_DIR = os.environ.get('DATA_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
RESULTS_DIR = os.environ.get('RESULTS_DIR') or os.path.join(DATA_DIR, 'web-scenarios')
BONUS_CSV = os.path.join(DATA_DIR, 'bonus-lat-lon-points.csv')
COMBOS_CSV = os.path.join(DATA_DIR, 'bonus-combos.csv')
# Road miles between bonuses, from buildRoadMiles.py, for the Road miles switch
ROAD_MILES_CSV = os.path.join(DATA_DIR, planRoute.ROAD_MILES_CSV)
# Archived runs, a folder for each time the list was archived, named for when
ARCHIVE_DIR = os.path.join(RESULTS_DIR, 'archives')
WORKERS = int(os.environ.get('PLANNER_WORKERS') or os.cpu_count())
GOOGLE_CHECK = os.environ.get('GOOGLE_CHECK', '').lower() in ('on', '1', 'true', 'yes')
GMAPS_API_KEY = os.environ.get('GMAPS_API_KEY', '')
if GOOGLE_CHECK:
    if not GMAPS_API_KEY:
        sys.exit("ERROR: GOOGLE_CHECK is on, so set GMAPS_API_KEY to your Google Maps API key")
    # Only needed for Google checks, so a site without them doesn't need requests
    import checkRoute
RALLY_TZ = ZoneInfo(os.environ.get('RALLY_TZ') or 'America/New_York')
# More waiting runs than this and new ones are turned away, so one person
# can't tie the server up for hours
MAX_QUEUED = 10

# The form: (name, label, default, lowest, highest, help)
NUMBERS = [
    ('hours', 'Time budget, hours', planRoute.DEFAULT_HOURS, 1, 12,
     'what the route is planned to fill, Rally HQ to Rally HQ; less than the deadline keeps a reserve'),
    ('deadline', 'Deadline, hours', planRoute.DEFAULT_HOURS, 1, 12,
     'when you must be back at HQ, after the start; confidence is measured against it'),
    ('speed', 'Average speed, MPH', planRoute.DEFAULT_SPEED, 20, 80,
     'with minutes per leg, Google checks of 2026 routes fit 50-54'),
    ('stop_minutes', 'Minutes at each bonus', 5, 0, 30,
     'stopped: parking, finding the sign, the photo, getting going again'),
    ('leg_minutes', 'Minutes per leg', planRoute.LEG_MINUTES, 0, 15,
     'driving off the main road and through local streets to the bonus, which the average speed misses; '
     'Google checks fit 3 (with about 54 MPH at road x1.23)'),
    ('window_margin', 'Bonus hours margin, minutes', planRoute.WINDOW_MARGIN, 0, 60,
     'reach a bonus with hours this long before it closes'),
    ('road_factor', 'Road factor', planRoute.DEFAULT_ROAD_FACTOR, 1.0, 2.0, 'road miles ÷ straight-line miles; Google checks gave 1.20-1.23'),
    ('front_load', 'Front-load', 0, 0, 5, '0 = most points; 1 trades some points for banking them earlier'),
    ('gas_miles', 'Gas stop every, miles', 175, 0, 500, '0 for no gas stops'),
    ('gas_minutes', 'Minutes per gas stop', 10, 0, 60, ''),
]
# Slow zones, picked in one dropdown, all off by default: (setting, label,
# default, help, zone). The setting names stay as they were so saved runs
# keep their IDs.
SLOW_ZONES = [
    ('slow_zone', 'Atlanta', False, 'inside I-285 plus about 5 miles at 25 MPH', planRoute.ATLANTA_SLOW_ZONE),
    ('athens_zone', 'Athens', False, 'about 3 miles around downtown Athens and UGA at 20 MPH, 5 more minutes a stop for parking',
     planRoute.ATHENS_SLOW_ZONE),
    ('savannah_zone', 'Savannah', False, '5 miles around downtown at 20 MPH, 5 more minutes a stop for parking',
     planRoute.SAVANNAH_SLOW_ZONE),
    ('augusta_zone', 'Augusta', False, '3 miles around downtown at 20 MPH, 5 more minutes a stop for parking',
     planRoute.AUGUSTA_SLOW_ZONE),
]
SWITCHES = [
    ('skip_timed', 'Leave out bonuses with hours', False, 'plan only the bonuses open all day'),
    ('avoid_atlanta', 'Avoid Atlanta', False,
     'leave out every bonus inside I-285 plus about 5 miles, e.g. for roadwork; legs across Atlanta still go at '
     'its slow-zone speed'),
    ('use_combos', 'Combo bonuses', True, 'add combo points for getting every bonus in one'),
    ('best_budget', 'Find the best time budget', False,
     'plan budgets from the deadline down and keep the one with the highest expected score under the late '
     'penalty; the time budget above is ignored; takes a few minutes'),
    ('in_order', 'In this order', False,
     'visit them first, in the order typed; the planner adds the rest of the day after them'),
    ('only', 'Only the must-visit bonuses', False,
     'route just those, adding nothing else; in the quickest order unless In this order is on'),
    ('road_miles', 'Road miles', False,
     'real road miles between bonuses (from a GraphHopper table, buildRoadMiles.py) instead of straight-line '
     'miles x the road factor; matched Google\'s leg times better at the same speed and leg minutes'),
    ('quick', 'Quick mode', False, 'beam search: about 4x faster and as good on the 2026 bonuses, but it may '
                                   'miss a better route; no front-load'),
]
# How the list of runs describes a switch that's off (the slow zones,
# leaving out timed bonuses, only and quick, off by default,
# are described when on)
SWITCHED_OFF = {'use_hours': 'bonus hours ignored', 'use_combos': 'no combos'}
# Bonus hours are always kept to (Leave out bonuses with hours is the way not
# to plan around them); use_hours stays a setting so saved runs keep their
# IDs, and runs from before, with it off, still show "bonus hours ignored"
DEFAULTS = {name: default for name, _, default, *_ in NUMBERS} | {name: on for name, _, on, *_ in SWITCHES + SLOW_ZONES} | {
    'use_hours': True,
    'must': '', 'start': planRoute.RALLY_START,
    'late_penalty': ','.join(f'{m:g}:{p:g}' for m, p in planRoute.LATE_PENALTY)}

app = Flask(__name__)
# Logins are a signed session cookie. The key comes from the password, so
# changing the password logs everyone out, and the cookie's name does too,
# so your site and the guest site on another port of the same machine
# (which share cookies) don't log each other out
_site_key = hmac.new(PASSWORD.encode(), b'rally-route-finder session', hashlib.sha256)
app.secret_key = _site_key.digest()
app.config.update(SESSION_COOKIE_NAME='rally_' + _site_key.hexdigest()[:10],
                  SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(days=30))


@app.context_processor
def google_setting():
    return {'google_enabled': GOOGLE_CHECK}


@app.context_processor
def browser_monitoring():
    # New Relic Browser's script for this page, or nothing; the agent then
    # knows not to add it again itself
    return {'browser_timing': newrelic.agent.get_browser_timing_header() if NEW_RELIC else ''}


def background_task(function):
    """Record each call as a New Relic background task, when it's on."""
    return newrelic.agent.background_task(name=function.__name__)(function) if NEW_RELIC else function

os.makedirs(RESULTS_DIR, exist_ok=True)
jobs = queue.Queue()
# What the run in progress is doing, from the planner's progress lines
progress = {}
# Runs asked to stop; the planner notices at its next progress line
stopping = set()


class Stopped(Exception):
    """Raised in the planner, through its progress lines, to stop a run."""


@app.before_request
def check_password():
    # Uptime monitors check /health without the password; it tells them
    # nothing else. The login page and its stylesheet are open too
    if request.path == '/health' or request.endpoint in ('login', 'static') or session.get('logged_in'):
        return None
    if request.method == 'GET':
        return redirect(url_for('login', next=request.full_path.rstrip('?')))
    return Response('Log in first', 401)


def safe_next(target):
    """Where to go after logging in: a page on this site, never elsewhere."""
    if target and target.startswith('/') and not target.startswith('//') and '\\' not in target:
        return target
    return url_for('index')


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if hmac.compare_digest(request.form.get('password', '').encode(), PASSWORD.encode()):
            session.clear()
            session.permanent = True
            session['logged_in'] = True
            return redirect(safe_next(request.form.get('next')))
        # Slows down guessing
        time.sleep(1)
        error = "That's not the password"
    return render_template('login.html', error=error, next=request.values.get('next', '')), 401 if error else 200


@app.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


def result_path(run_id, extension='json'):
    if not run_id.isalnum():
        abort(404)
    return os.path.join(RESULTS_DIR, f"{run_id}.{extension}")


def load_run(run_id):
    try:
        with open(result_path(run_id)) as f:
            return json.load(f)
    except FileNotFoundError:
        abort(404)


def save_run(run):
    # Write then rename, so a page never reads a half-written file
    path = result_path(run['id'])
    with open(path + '.tmp', 'w') as f:
        json.dump(run, f)
    os.replace(path + '.tmp', path)


# Held while a run's file is read, changed and saved again
save_lock = threading.Lock()
# One Google check at a time, so a double click can't pay for the same check twice
check_lock = threading.Lock()


def save_worker_copy(run):
    """Save the worker's copy of a run, keeping any name or favorite given
    to it since the worker loaded it."""
    with save_lock:
        saved = load_run(run['id'])
        run['name'] = saved.get('name', '')
        run['favorite'] = saved.get('favorite', False)
        save_run(run)


def all_runs():
    runs = []
    for name in os.listdir(RESULTS_DIR):
        if name.endswith('.json'):
            with open(os.path.join(RESULTS_DIR, name)) as f:
                runs.append(json.load(f))
    return sorted(runs, key=lambda run: run['created'], reverse=True)


def data_fingerprint(settings):
    """Changes whenever the bonus or combo file does (or the road miles
    table, for a run that uses it), so old results aren't reused for new
    data."""
    digest = hashlib.sha256()
    for path in (BONUS_CSV, COMBOS_CSV) + ((ROAD_MILES_CSV,) if settings.get('road_miles') else ()):
        if os.path.exists(path):
            with open(path, 'rb') as f:
                digest.update(f.read())
    return digest.hexdigest()


def read_form(form):
    """The settings from the form, checked; raises ValueError with a message
    for the person if something's out of range."""
    settings = {}
    for name, label, _, low, high, _ in NUMBERS:
        try:
            value = float(form.get(name, ''))
        except ValueError:
            raise ValueError(f"{label}: enter a number")
        if not low <= value <= high:
            raise ValueError(f"{label}: must be from {low:g} to {high:g}")
        settings[name] = value
    for name, *_ in SWITCHES + SLOW_ZONES:
        settings[name] = form.get(name) == 'on'
    settings['use_hours'] = True
    try:
        settings['start'] = planRoute.start_time(form.get('start', '').strip())
    except argparse.ArgumentTypeError as error:
        raise ValueError(f"Rally start: {error}")
    try:
        tiers = planRoute.parse_late_penalty(form.get('late_penalty', '').strip())
    except argparse.ArgumentTypeError:
        raise ValueError("Late penalty: enter minutes:percent pairs, e.g. 15:25,30:50")
    settings['late_penalty'] = ','.join(f'{m:g}:{p:g}' for m, p in tiers)
    settings['must'] = ','.join(code.strip().upper() for code in form.get('must', '').split(',') if code.strip())
    if settings['hours'] > settings['deadline'] and not settings['best_budget']:
        raise ValueError("Time budget: must be no more than the deadline")
    if settings['in_order'] and not settings['must']:
        raise ValueError("In this order: list the bonuses in Must visit")
    if not settings['in_order']:
        # Off is left out, so runs from before the switch keep their IDs
        del settings['in_order']
    if settings['road_miles'] and not os.path.exists(ROAD_MILES_CSV):
        raise ValueError("Road miles: there's no road miles table on the server yet")
    if not settings['avoid_atlanta']:
        # Off is left out, so runs from before the switch keep their IDs
        del settings['avoid_atlanta']
    if not settings['road_miles']:
        # Off is left out, so runs from before the switch keep their IDs
        del settings['road_miles']
    if settings['only'] and not settings['must']:
        raise ValueError("Only the must-visit bonuses: list the bonuses in Must visit")
    if settings['quick'] and settings['front_load']:
        raise ValueError("Quick mode: set Front-load to 0, since quick mode doesn't support it")
    if settings['best_budget'] and settings['front_load']:
        raise ValueError("Find the best time budget: set Front-load to 0, since it plans in quick mode")
    if settings['best_budget'] and settings['only']:
        raise ValueError("Find the best time budget: turn off Only the must-visit bonuses")
    return settings


def describe(settings):
    """A short line for the list of runs, e.g. '9.5 h, 46 MPH, 4 min stops, road x1.22'."""
    # Runs from before the deadline setting had it at the time budget
    deadline = settings.get('deadline', settings['hours'])
    hours = (f"best budget for {deadline:g} h" if settings.get('best_budget')
             else f"{settings['hours']:g} h" + (f" of {deadline:g}" if deadline > settings['hours'] else ''))
    parts = [hours,
             f"{settings['speed']:g} MPH", f"{settings['stop_minutes']:g} min stops",
             'road miles' if settings.get('road_miles') else f"road ×{settings['road_factor']:g}"]
    # Runs from before these settings had neither
    if settings.get('leg_minutes'):
        parts.append(f"{settings['leg_minutes']:g} min legs")
    if settings.get('window_margin') and settings['use_hours'] and not settings.get('skip_timed'):
        parts.append(f"hours margin {settings['window_margin']:g} min")
    if settings.get('late_penalty', DEFAULTS['late_penalty']) != DEFAULTS['late_penalty']:
        parts.append(f"late penalty {settings['late_penalty'] or 'DNF if late'}")
    if settings['front_load']:
        parts.append(f"front-load {settings['front_load']:g}")
    if settings['gas_miles'] != 175 or settings['gas_minutes'] != 10:
        parts.append(f"gas {settings['gas_minutes']:g} min / {settings['gas_miles']:g} mi" if settings['gas_miles']
                     else 'no gas stops')
    if settings['start'] != planRoute.RALLY_START:
        parts.append(f"start {settings['start']}")
    if settings.get('first'):
        # Runs from before the form asked for must-visit bonuses instead
        parts.append(f"first {settings['first']}")
    if settings.get('must'):
        parts.append(f"must visit {settings['must'].replace(',', ', ')}"
                     + (' in that order' if settings.get('in_order') else ''))
    parts += [text for name, text in SWITCHED_OFF.items() if not settings[name]
              and not (name == 'use_hours' and settings.get('skip_timed'))]
    if settings.get('skip_timed'):
        parts.append('bonuses with hours left out')
    if settings.get('avoid_atlanta'):
        parts.append('Atlanta avoided')
    zones = [label for name, label, *_ in SLOW_ZONES if settings.get(name)]
    if zones:
        names = zones[0] if len(zones) == 1 else ', '.join(zones[:-1]) + ' and ' + zones[-1]
        parts.append(f"{names} slow zone{'s' if len(zones) > 1 else ''}")
    # Runs from before the avoid options became slow zones
    if settings.get('avoid_savannah'):
        parts.append('avoid Savannah')
    if settings.get('avoid_augusta'):
        parts.append('avoid Augusta')
    if settings.get('only'):
        parts.append('only those')
    if settings.get('quick'):
        parts.append('quick mode')
    return ', '.join(parts)


def planner_args(settings):
    """The command-line arguments planRoute's helpers read, from a run's settings."""
    if settings.get('in_order'):
        # Must-visit bonuses in a fixed order are the planner's first stops
        first, must = settings['must'], None
    else:
        first, must = settings.get('first'), settings.get('must')
    return argparse.Namespace(first=first, must=must, only=settings.get('only'),
                              skip_timed=settings.get('skip_timed', False),
                              avoid_atlanta=settings.get('avoid_atlanta', False),
                              gas_miles=settings['gas_miles'], gas_minutes=settings['gas_minutes'],
                              combos=COMBOS_CSV, ignore_combos=not settings['use_combos'])


def run_slow_zones(settings):
    """The slow zones a run's settings picked."""
    zones = [zone for name, *_, zone in SLOW_ZONES if settings.get(name)]
    if settings.get('avoid_atlanta') and planRoute.ATLANTA_SLOW_ZONE not in zones:
        # Legs that cut across Atlanta are still slow there
        zones.append(planRoute.ATLANTA_SLOW_ZONE)
    return zones


def make_planner(settings, args):
    """A Planner for a run's settings, with its must-visit stops and combos;
    returns (planner, bonuses, slow zones). Exits (SystemExit) on bad input,
    e.g. an unknown must-visit code."""
    hq, bonuses = planRoute.load_bonuses(BONUS_CSV)
    bonuses = planRoute.planned_bonuses(bonuses, args)
    slow_zones = run_slow_zones(settings)
    planner = planRoute.Planner(hq, bonuses, settings['hours'], settings['speed'], settings['stop_minutes'],
                                settings['road_factor'], settings['front_load'], slow_zones,
                                settings['gas_miles'], settings['gas_minutes'], settings['start'],
                                settings['use_hours'], leg_minutes=settings.get('leg_minutes', 0),
                                window_margin=settings.get('window_margin', 0) if settings['use_hours'] else 0,
                                deadline=settings.get('deadline', settings['hours']),
                                late_penalty=planRoute.parse_late_penalty(
                                    settings.get('late_penalty', DEFAULTS['late_penalty'])),
                                road_miles=planRoute.load_road_miles(ROAD_MILES_CSV)
                                if settings.get('road_miles') else None)
    planRoute.apply_first(planner, args)
    planRoute.apply_combos(planner, args)
    return planner, bonuses, slow_zones


@background_task
def plan(run):
    """Run the planner for one saved run, and save the result or the error."""
    settings = run['settings']
    if NEW_RELIC:
        newrelic.agent.add_custom_attributes([('run_id', run['id']), ('hours', settings['hours']),
                                              ('quick', bool(settings.get('quick'))),
                                              ('must', settings.get('must') or '')])
    args = planner_args(settings)
    started = time.monotonic()
    try:
        planner, bonuses, slow_zones = make_planner(settings, args)
        budgets = None
        if settings.get('best_budget'):
            route, budgets = planRoute.best_budget(planner, lambda p: planRouteSearch.quick_route(p, WORKERS))
            if not settings.get('quick'):
                # The full search may do better on the budget found
                full = planner.solve(planRoute.START_WEIGHTS, 6, WORKERS)
                if planRoute.simulate(planner, full)['expected'] > planRoute.simulate(planner, route)['expected']:
                    route = full
        elif settings.get('quick'):
            route = planRouteSearch.quick_route(planner, WORKERS)
        else:
            route = planner.solve(planRoute.START_WEIGHTS, 6, WORKERS)
    except Stopped:
        run.update(status='stopped', error="Stopped before it finished")
        save_worker_copy(run)
        return
    except SystemExit as stop:
        run.update(status='error', error=str(stop.code).removeprefix('ERROR: ').replace('--must', 'Must visit')
                   .replace('--only', 'Only the must-visit bonuses')
                   .replace('--first', 'Must visit, in this order' if settings.get('in_order') else 'First stops'))
        save_worker_copy(run)
        return
    except Exception as error:
        run.update(status='error', error=f"The planner failed: {error}")
        save_worker_copy(run)
        raise
    finish_run(run, planner, route, bonuses, slow_zones, args, round(time.monotonic() - started))
    if budgets:
        run['budgets'] = budgets
    save_worker_copy(run)


def confidence(planner, route):
    """The run's confidence fields: the share of simulated days that go as
    planned, when half and 90% of them are back, and the line describing it."""
    sim = planRoute.simulate(planner, route)
    return dict(confidence=round(sim['confidence'] * 100), expected=round(sim['expected']), confidence_text=planRoute.describe_confidence(planner, sim),
                back_by=dict(half=planRoute.time_of_day(planner, sim['finish_p50']),
                             most=planRoute.time_of_day(planner, sim['finish_p90']),
                             # For sorting: minutes after midnight 90% are back by
                             most_minutes=round((planRoute.clock_hours(planner.start) + sim['finish_p90']) * 60)))


def needs_confidence(run):
    """True for a run from before confidence was simulated, or before the
    deadline was a setting of its own."""
    return run['status'] == 'done' and ('expected' not in run or 'deadline' not in run['settings'])


def add_confidence(run_id):
    """Give a run from before confidence was simulated, or before the
    deadline setting, its confidence, once. Such a run's deadline is the
    form's default or its time budget, whichever is later. Left off if the
    bonus data has changed so its stops can't be found."""
    with save_lock:
        run = load_run(run_id)
        if not needs_confidence(run):
            return run
        run['settings'].setdefault('deadline', max(run['settings']['hours'], planRoute.DEFAULT_HOURS))
        try:
            planner, _, _ = make_planner(run['settings'], planner_args(run['settings']))
            index = {place['code']: i for i, place in enumerate(planner.places) if i}
            route = [index[leg['code']] for leg in run['legs'] if leg['code'] in index or 'Rally' not in leg['code']]
        except (SystemExit, KeyError):
            return run
        run.update(confidence(planner, route))
        save_run(run)
        return run


def finish_run(run, planner, route, bonuses, slow_zones, args, seconds):
    """Fill in a run's route, table and GPX file, and mark it done."""
    settings = run['settings']
    legs = list(planRoute.route_legs(planner, route))
    planRoute.write_gpx(planner, route, result_path(run['id'], 'gpx'))
    run.update(status='done', seconds=seconds,
               finished=datetime.now(timezone.utc).isoformat(timespec='seconds'),
               points=legs[-1].score, stops=len(route), miles=round(legs[-1].miles),
               hours=round(legs[-1].hours, 2), budget=planner.max_hours,
               settings_lines=[f"{len(bonuses)} bonuses, {planRoute.describe_gas(args)}, "
                               f"{planRoute.describe_slow_zones(slow_zones)}, {planRoute.describe_first(planner)}",
                               planRoute.describe_hours(planner), planRoute.describe_combos(planner)]
                              + (["Quick mode: beam search (width 2000, branch 12), then planRoute.py's "
                                  "drop-and-reinsert search"] if settings.get('quick') else []),
               summary=planRoute.summary_lines(planner, route, legs),
               **confidence(planner, route),
               legs=[dict(code=leg.place['code'], state=leg.place['state'], points=leg.place['points'],
                          lat=leg.place['lat'], lon=leg.place['lon'], leg_miles=round(leg.leg_miles, 1),
                          miles=round(leg.miles, 1), leave=round(leg.hours, 2),
                          arrive=planRoute.time_of_day(planner, leg.arrive), score=leg.score,
                          notes=planRoute.leg_notes(planner, leg))
                     for leg in legs])


def worker():
    # The planner reports progress through planRoute.progress; show it on the
    # run's page instead of a terminal
    while True:
        run_id = jobs.get()

        def report(text, run_id=run_id):
            # Raising here unwinds the planner, which shuts down its worker processes
            if run_id in stopping:
                raise Stopped
            progress[run_id] = text.strip()

        planRoute.progress = report
        with save_lock:
            path = result_path(run_id)
            # Skip a run stopped or deleted while it waited ('running' is one
            # the server was in the middle of when it last stopped)
            if not os.path.exists(path) or load_run(run_id)['status'] not in ('queued', 'running'):
                continue
            run = load_run(run_id)
            run['status'] = 'running'
            save_run(run)
        try:
            plan(run)
        except Exception:
            app.logger.exception(f"run {run_id} failed")
        finally:
            progress.pop(run_id, None)
            stopping.discard(run_id)


# Runs waiting when the server last stopped go back in the queue
for waiting in sorted((run for run in all_runs() if run['status'] in ('queued', 'running')),
                      key=lambda run: run['created']):
    jobs.put(waiting['id'])
worker_thread = threading.Thread(target=worker, daemon=True)
worker_thread.start()


def heartbeat():
    """Report to New Relic every minute, so the app keeps reporting when
    nobody's using it: runs waiting, and whether one is running."""
    while True:
        time.sleep(60)
        application = newrelic.agent.application()
        newrelic.agent.record_custom_metric('Custom/Heartbeat/QueuedRuns', jobs.qsize(), application=application)
        newrelic.agent.record_custom_metric('Custom/Heartbeat/Running', 1 if progress else 0, application=application)


if NEW_RELIC:
    threading.Thread(target=heartbeat, daemon=True).start()


@app.get('/health')
def health():
    """For uptime monitors: 200 while the app can plan runs, 503 if the
    thread that runs the planner has died."""
    if NEW_RELIC:
        # A monitor checking every minute shouldn't swamp the real traffic
        newrelic.agent.ignore_transaction()
    if not worker_thread.is_alive():
        return {'status': 'planner stopped'}, 503
    return {'status': 'ok'}


@app.get('/')
def index():
    settings = DEFAULTS
    if request.args.get('from'):
        settings = DEFAULTS | load_run(request.args['from'])['settings']
    runs = [add_confidence(run['id']) if needs_confidence(run) else run
            for run in all_runs()]
    return render_template('index.html', numbers=NUMBERS, switches=SWITCHES, slow_zones=SLOW_ZONES, settings=settings,
                           runs=runs, describe=describe, error=None, archive_count=len(os.listdir(ARCHIVE_DIR)) if os.path.isdir(ARCHIVE_DIR) else 0,
                           has_data=os.path.exists(BONUS_CSV))


@app.post('/run')
def start_run():
    try:
        settings = read_form(request.form)
    except ValueError as error:
        return render_template('index.html', numbers=NUMBERS, switches=SWITCHES, slow_zones=SLOW_ZONES,
                               settings=DEFAULTS | request.form.to_dict()
                               | {name: request.form.get(name) == 'on' for name, *_ in SWITCHES + SLOW_ZONES},
                               runs=all_runs(), describe=describe,
                               error=str(error), has_data=os.path.exists(BONUS_CSV)), 400
    if not os.path.exists(BONUS_CSV):
        abort(503, "No bonus data on the server yet")
    key = json.dumps(settings, sort_keys=True) + data_fingerprint(settings)
    run_id = hashlib.sha256(key.encode()).hexdigest()[:12]
    path = result_path(run_id)
    if os.path.exists(path):
        run = load_run(run_id)
        if run['status'] not in ('error', 'stopped'):
            # Same settings and data as an earlier run: show that one
            return redirect(url_for('show_run', run_id=run_id))
    if jobs.qsize() >= MAX_QUEUED:
        abort(503, f"{MAX_QUEUED} runs are already waiting; try again in a few minutes")
    save_run(dict(id=run_id, settings=settings, status='queued', name=request.form.get('name', '').strip()[:60],
                  created=datetime.now(timezone.utc).isoformat(timespec='seconds')))
    jobs.put(run_id)
    return redirect(url_for('show_run', run_id=run_id))


def run_state(run):
    """Status for the run's page while it waits or runs."""
    if run['status'] == 'queued':
        ahead = sum(1 for other in all_runs() if other['status'] in ('queued', 'running')
                    and other['created'] < run['created'])
        return f"Waiting: {ahead} run{'s' if ahead != 1 else ''} ahead of this one"
    if run['status'] == 'running':
        return 'Stopping…' if run['id'] in stopping else progress.get(run['id'], 'Starting')
    return ''


@app.get('/run/<run_id>')
def show_run(run_id):
    return render_run(load_run(run_id))


def render_run(run, google_error=None, status=200):
    run_id = run['id']
    if any('fit' not in check for check in run.get('checks', [])) and os.path.exists(BONUS_CSV):
        # Checks from before fits were made get theirs now, once
        with save_lock:
            run = load_run(run_id)
            for check in run.get('checks', []):
                if 'fit' not in check:
                    check['fit'] = fit_check(run, check)
            save_run(run)
    if needs_confidence(run) and os.path.exists(BONUS_CSV):
        run = add_confidence(run_id)
    bonuses = []
    if run['status'] == 'done' and os.path.exists(BONUS_CSV):
        _, bonuses = planRoute.load_bonuses(BONUS_CSV)
    # Neighbours in the scenario list's order, newest first
    ids = [r['id'] for r in all_runs()]
    at = ids.index(run_id) if run_id in ids else 0
    newer = ids[at - 1] if at > 0 else None
    older = ids[at + 1] if at + 1 < len(ids) else None
    return render_template('run.html', run=run, state=run_state(run), describe=describe,
                           newer=newer, older=older, position=at + 1, total=len(ids),
                           google_error=google_error, google_form=request.form if google_error else {},
                           highway_mph=checkRoute.HIGHWAY_MPH if GOOGLE_CHECK else None,
                           bonuses=[dict(code=b['code'], lat=b['lat'], lon=b['lon'], points=b['points'])
                                    for b in bonuses]), status


def google_check(run, depart, check_id, faster=None):
    """Check a finished run's route with the Google Maps Routes API, as
    checkRoute.py does, and return the result to save with the run. Without
    depart it's one request with no traffic; with depart (a datetime), one
    request per leg with Google's traffic forecast. faster drives faster than
    Google's times, as checkRoute.make_faster makes it. Exits (SystemExit)
    with a message if Google refuses."""
    settings = run['settings']
    places = [dict(code=leg['code'], lat=leg['lat'], lon=leg['lon'], points=leg['points'], state=leg['state'])
              for leg in run['legs']]
    start = f"{depart:%H:%M}" if depart else settings['start']
    windows = checkRoute.bonus_windows(BONUS_CSV, start) if settings['use_hours'] else {}
    combos = planRoute.load_combos(COMBOS_CSV) if settings['use_combos'] else []
    stop_hours, gas_hours = settings['stop_minutes'] / 60, settings['gas_minutes'] / 60
    zones = run_slow_zones(settings)
    if depart:
        legs, polylines = checkRoute.fetch_with_traffic(GMAPS_API_KEY, places, depart, stop_hours,
                                                        settings['gas_miles'], gas_hours, windows, faster, zones)
        source = f"with traffic, leaving {depart:%a %b} {depart.day} {depart:%H:%M}"
        requests_made = len(places) - 1
    else:
        legs, polylines = checkRoute.fetch_batched(GMAPS_API_KEY, places, faster)
        source = "no traffic"
        requests_made = math.ceil((len(places) - 1) / (checkRoute.MAX_WAYPOINTS + 1))
    if faster:
        source += f", {checkRoute.describe_faster(faster)}"
    rows = list(checkRoute.timeline(places, legs, stop_hours, settings['gas_miles'], gas_hours, windows, combos,
                                    zones))
    begin = planRoute.clock_hours(start)

    def time_of_day(hours):
        minutes = round((begin + hours) * 60)
        return f"{minutes // 60 % 24}:{minutes % 60:02}"

    checkRoute.write_gpx(rows, polylines, settings['hours'], f"Google, {source}",
                         result_path(run['id'], f'google-{check_id}.gpx'))
    last = rows[-1]
    return dict(id=check_id, source=source, created=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                requests=requests_made, points=last.score, miles=round(last.miles), hours=round(last.arrive, 2),
                fits=last.arrive <= settings['hours'],
                summary=checkRoute.summary_lines(places, legs, rows, windows, combos, settings['hours'],
                                                 settings['gas_miles'], time_of_day,
                                                 settings.get('leg_minutes', planRoute.LEG_MINUTES)),
                rows=[dict(code=row.place['code'], state=row.place['state'], points=row.place['points'],
                           line_miles=round(planRoute.haversine_miles(rows[n - 1].place, row.place), 1) if n else 0,
                           road_miles=round(row.leg_miles, 1), miles=round(row.miles, 1),
                           drive=round(row.leg_hours * 60), arrive=time_of_day(row.arrive), leave=round(row.leave, 2),
                           score=row.score, missed=row.missed, notes=checkRoute.row_notes(row, windows))
                      for n, row in enumerate(rows)],
                # Google's roads for the map, to about 1 m
                track=[[round(lat, 5), round(lon, 5)] for polyline in polylines
                       for lat, lon in checkRoute.decode_polyline(polyline)])


def fit_check(run, check):
    """Stops to drop so a Google check's route fits the time and makes its
    bonuses' hours, from the check's saved legs (no more requests), as
    checkRoute.fit_to_time finds them: {codes kept in order, dropped, points,
    hours, miles}, or None if dropping doesn't help."""
    settings = run['settings']
    rows = check['rows']
    places = [dict(code=row['code'], state=row['state'], points=row['points'], lat=leg['lat'], lon=leg['lon'])
              for row, leg in zip(rows, run['legs'])]
    legs = [(row['road_miles'], row['drive'] / 60) for row in rows[1:]]
    # A traffic check's id starts with its departure, YYYYmmddHHMM, and its
    # bonus hours count from then
    start = f"{check['id'][8:10]}:{check['id'][10:12]}" if check['id'][:1].isdigit() else settings['start']
    windows = checkRoute.bonus_windows(BONUS_CSV, start) if settings['use_hours'] else {}
    combos = planRoute.load_combos(COMBOS_CSV) if settings['use_combos'] else []
    stop_hours, gas_hours = settings['stop_minutes'] / 60, settings['gas_minutes'] / 60
    zones = run_slow_zones(settings)
    fitted = checkRoute.fit_to_time(places, legs, stop_hours, settings['gas_miles'], gas_hours, windows, combos,
                                    settings['hours'], settings.get('leg_minutes', planRoute.LEG_MINUTES), zones)
    if not fitted:
        return None
    fit_places, fit_legs = fitted
    last = list(checkRoute.timeline(fit_places, fit_legs, stop_hours, settings['gas_miles'], gas_hours,
                                    windows, combos, zones))[-1]
    kept = {p['code'] for p in fit_places}
    return dict(points=last.score, hours=round(last.arrive, 2), miles=round(last.miles),
                codes=[p['code'] for p in fit_places[1:-1]],
                dropped=[dict(code=p['code'], points=p['points']) for p in places[1:-1] if p['code'] not in kept])


@app.post('/run/<run_id>/google')
def start_google_check(run_id):
    if not GOOGLE_CHECK:
        abort(404)
    run = load_run(run_id)
    if run['status'] != 'done':
        abort(400, "Only a finished route can be checked")
    depart = None
    text = request.form.get('depart', '').strip()
    if text:
        try:
            depart = datetime.fromisoformat(text).replace(tzinfo=RALLY_TZ, second=0, microsecond=0)
        except ValueError:
            return render_run(run, "Departure: enter a date and time", 400)
        if depart <= datetime.now(RALLY_TZ):
            return render_run(run, "Departure: Google only forecasts traffic for future times", 400)
    percents = {}
    for field in ('highway_faster', 'surface_faster'):
        try:
            percents[field] = int(request.form.get(field, '').strip() or 0)
        except ValueError:
            return render_run(run, "Faster: enter a whole percent, e.g. 10, or -5 for slower", 400)
        if not -50 <= percents[field] <= 100:
            return render_run(run, "Faster: the percents must be from -50 to 100", 400)
    faster = checkRoute.make_faster(percents['highway_faster'], percents['surface_faster'])
    check_id = f"{depart:%Y%m%d%H%M}" if depart else 'notraffic'
    if faster:
        # Letters and digits only, for the GPX link: notrafficH10S5, H10Sm5 for 5% slower
        check_id += ''.join(f"{letter}{percent}".replace('-', 'm')
                            for letter, percent in zip('HS', faster[:2]))
    with check_lock:
        # Checked before? Show that one rather than paying Google again
        if check_id not in [check['id'] for check in load_run(run_id).get('checks', [])]:
            try:
                check = google_check(run, depart, check_id, faster)
                check['fit'] = fit_check(run, check)
            except SystemExit as stop:
                return render_run(run, str(stop.code).removeprefix('ERROR: '), 502)
            except Exception as error:
                app.logger.exception(f"Google check of run {run_id} failed")
                return render_run(run, f"The Google check failed: {error}", 502)
            with save_lock:
                run = load_run(run_id)
                run['checks'] = [check] + run.get('checks', [])
                save_run(run)
    return redirect(url_for('show_run', run_id=run_id, _anchor=f'google-{check_id}'))


@app.post('/run/<run_id>/google-<check_id>/fit')
def make_fitted_run(run_id, check_id):
    """A new scenario with the stops a Google check's fit kept, in the same
    order, timed by the planner, ready to check with Google itself."""
    source = load_run(run_id)
    check = next((c for c in source.get('checks', []) if c['id'] == check_id), None)
    if check is None or not check.get('fit'):
        abort(404)
    settings = source['settings'] | dict(must=','.join(check['fit']['codes']), only=True, quick=False)
    settings.pop('first', None)
    key = json.dumps(settings, sort_keys=True) + data_fingerprint(settings) + 'fit'
    new_id = hashlib.sha256(key.encode()).hexdigest()[:12]
    if not os.path.exists(result_path(new_id)):
        args = planner_args(settings)
        try:
            planner, bonuses, slow_zones = make_planner(settings, args)
        except SystemExit as stop:
            return render_run(source, str(stop.code).removeprefix('ERROR: '), 400)
        index = {place['code']: b for b, place in enumerate(planner.places)}
        route = [index[code] for code in check['fit']['codes']]
        dropped = ', '.join(d['code'] for d in check['fit']['dropped'])
        run = dict(id=new_id, settings=settings, status='queued',
                   name=f"{source.get('name') or source['id']} fitted"[:60],
                   fitted=dict(run=run_id, check=check_id, dropped=dropped),
                   created=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        finish_run(run, planner, route, bonuses, slow_zones, args, 0)
        run['settings_lines'].insert(0, f"Fitted to Google's times from {run_id} ({check['source']}): "
                                        f"dropped {dropped}; stops in the same order")
        with save_lock:
            save_run(run)
    return redirect(url_for('show_run', run_id=new_id))


@app.get('/run/<run_id>/google-<check_id>.gpx')
def google_gpx(run_id, check_id):
    if not check_id.isalnum():
        abort(404)
    run = load_run(run_id)
    check = next((c for c in run.get('checks', []) if c['id'] == check_id), None)
    path = result_path(run_id, f'google-{check_id}.gpx')
    if check is None or not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True,
                     download_name=f"route-google-{run_id}-{check['points']}pts.gpx")


@app.post('/run/<run_id>/stop')
def stop_run(run_id):
    with save_lock:
        run = load_run(run_id)
        if run['status'] == 'queued':
            run.update(status='stopped', error="Stopped before it started")
            save_run(run)
        elif run['status'] == 'running':
            stopping.add(run_id)
    return redirect(url_for('show_run', run_id=run_id))


@app.post('/run/<run_id>/delete')
def delete_run(run_id):
    with save_lock:
        run = load_run(run_id)
        if run['status'] in ('queued', 'running'):
            abort(409, "Stop the run before deleting it")
        # The run, its GPX and any Google checks' GPX files
        for path in glob.glob(glob.escape(result_path(run_id, '')) + '*'):
            os.remove(path)
    return redirect(url_for('index'))


def archive_path(name):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-\d{6}', name):
        abort(404)
    return os.path.join(ARCHIVE_DIR, name)


def run_files(folder, run_id):
    """A run's files in folder: its JSON, its GPX and any Google checks' GPX."""
    return glob.glob(os.path.join(glob.escape(folder), glob.escape(run_id) + '.*'))


def all_archives():
    """Each archive's name and summary, newest first."""
    archives = []
    if os.path.isdir(ARCHIVE_DIR):
        for name in sorted(os.listdir(ARCHIVE_DIR), reverse=True):
            folder = os.path.join(ARCHIVE_DIR, name)
            runs = []
            for path in glob.glob(os.path.join(glob.escape(folder), '*.json')):
                with open(path) as f:
                    runs.append(json.load(f))
            done = [run for run in runs if run['status'] == 'done']
            archives.append(dict(name=name, runs=len(runs), favorites=sum(1 for run in runs if run.get('favorite')),
                                 best=max((run['points'] for run in done), default=None),
                                 archived=datetime.strptime(name, '%Y-%m-%d-%H%M%S')
                                 .replace(tzinfo=timezone.utc).isoformat(timespec='seconds'),
                                 present=sum(1 for run in runs if os.path.exists(result_path(run['id'])))))
    return archives


@app.post('/archive')
def archive_runs():
    """Move every run that isn't waiting or running into a new archive."""
    with save_lock:
        runs = [run for run in all_runs() if run['status'] not in ('queued', 'running')]
        if runs:
            name = datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')
            folder = os.path.join(ARCHIVE_DIR, name)
            os.makedirs(folder, exist_ok=True)
            for run in runs:
                for path in run_files(RESULTS_DIR, run['id']):
                    shutil.move(path, folder)
    return redirect(url_for('index'))


@app.get('/archives')
def show_archives():
    return render_template('archives.html', archives=all_archives(),
                           restored=request.args.get('restored'), skipped=request.args.get('skipped'))


@app.post('/archives/<name>/restore')
def restore_archive(name):
    """Move an archive's runs back into the list. A run whose settings were
    planned again since it was archived, so it's in the list already, stays
    in the archive and the list's copy is kept."""
    folder = archive_path(name)
    if not os.path.isdir(folder):
        abort(404)
    restored = skipped = 0
    with save_lock:
        for path in glob.glob(os.path.join(glob.escape(folder), '*.json')):
            run_id = os.path.basename(path)[:-len('.json')]
            if os.path.exists(result_path(run_id)):
                skipped += 1
                continue
            for file in run_files(folder, run_id):
                shutil.move(file, RESULTS_DIR)
            restored += 1
        if not os.listdir(folder):
            os.rmdir(folder)
    return redirect(url_for('show_archives', restored=restored, skipped=skipped))


@app.post('/run/<run_id>/name')
def rename_run(run_id):
    with save_lock:
        run = load_run(run_id)
        run['name'] = request.form.get('name', '').strip()[:60]
        save_run(run)
    return redirect(url_for('show_run', run_id=run_id))


@app.post('/run/<run_id>/favorite')
def favorite_run(run_id):
    with save_lock:
        run = load_run(run_id)
        run['favorite'] = not run.get('favorite', False)
        save_run(run)
    # Back to the list or the scenario page, wherever the star was clicked
    if request.form.get('back') == 'index':
        return redirect(url_for('index'))
    return redirect(url_for('show_run', run_id=run_id))


@app.get('/run/<run_id>/status')
def run_status(run_id):
    run = load_run(run_id)
    return {'status': run['status'], 'state': run_state(run)}


@app.get('/run/<run_id>.gpx')
def run_gpx(run_id):
    run = load_run(run_id)
    if run['status'] != 'done':
        abort(404)
    return send_file(result_path(run_id, 'gpx'), as_attachment=True,
                     download_name=f"route-{run_id}-{run['points']}pts.gpx")
