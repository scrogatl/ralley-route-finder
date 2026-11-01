"""
A small password-protected web app for running planRoute.py scenarios.

People fill in a form with the planner's settings, the run goes in a queue
(one at a time, since each run uses every CPU core), and the result page
shows the route table, a map and a GPX download. Every run is saved, so the
home page lists them all to compare, and the same settings on the same data
return the saved result instantly. No Google API calls.

Environment:
    APP_PASSWORD     required; the password for the whole site (any user name)
    DATA_DIR         folder with bonus-lat-lon-points.csv and bonus-combos.csv
                     from extractDatafromGPX.py (default: the repo folder)
    RESULTS_DIR      where runs are saved (default: DATA_DIR/web-scenarios)
    PLANNER_WORKERS  CPU cores per run (default: all)

    APP_PASSWORD=secret flask --app webapp/app.py run    # to try it locally
"""
import argparse, hashlib, hmac, json, os, queue, sys, threading, time
from datetime import datetime, timezone
from flask import Flask, Response, abort, redirect, render_template, request, send_file, url_for

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import planRoute

PASSWORD = os.environ.get('APP_PASSWORD') or sys.exit("ERROR: set APP_PASSWORD to the site's password")
DATA_DIR = os.environ.get('DATA_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
RESULTS_DIR = os.environ.get('RESULTS_DIR') or os.path.join(DATA_DIR, 'web-scenarios')
BONUS_CSV = os.path.join(DATA_DIR, 'bonus-lat-lon-points.csv')
COMBOS_CSV = os.path.join(DATA_DIR, 'bonus-combos.csv')
WORKERS = int(os.environ.get('PLANNER_WORKERS') or os.cpu_count())
# More waiting runs than this and new ones are turned away, so one person
# can't tie the server up for hours
MAX_QUEUED = 10

# The form: (name, label, default, lowest, highest, help)
NUMBERS = [
    ('hours', 'Time budget, hours', 9.5, 1, 12, 'Rally HQ to Rally HQ'),
    ('speed', 'Average speed, MPH', 45, 20, 80, 'Google checks of 2026 routes averaged 46-47'),
    ('stop_minutes', 'Minutes at each bonus', 5, 0, 30, 'to take its picture'),
    ('road_factor', 'Road factor', 1.0, 1.0, 2.0, 'road miles ÷ straight-line miles; Google checks gave 1.20-1.23'),
    ('front_load', 'Front-load', 0, 0, 5, '0 = most points; 1 trades some points for banking them earlier'),
    ('gas_miles', 'Gas stop every, miles', 175, 0, 500, '0 for no gas stops'),
    ('gas_minutes', 'Minutes per gas stop', 10, 0, 60, ''),
]
SWITCHES = [
    ('slow_zone', 'Atlanta slow zone', True, 'inside I-285 plus about 5 miles at 25 MPH'),
    ('use_hours', 'Bonus hours', True, "only count bonuses reached while they're open"),
    ('use_combos', 'Combo bonuses', True, 'add combo points for getting every bonus in one'),
]
# How the list of runs describes a switch that's off
SWITCHED_OFF = {'slow_zone': 'no Atlanta slow zone', 'use_hours': 'bonus hours ignored', 'use_combos': 'no combos'}
DEFAULTS = {name: default for name, _, default, *_ in NUMBERS} | {name: on for name, _, on, _ in SWITCHES} | {
    'must': '', 'start': planRoute.RALLY_START}

app = Flask(__name__)
os.makedirs(RESULTS_DIR, exist_ok=True)
jobs = queue.Queue()
# What the run in progress is doing, from the planner's progress lines
progress = {}


@app.before_request
def check_password():
    auth = request.authorization
    if not auth or not hmac.compare_digest((auth.password or '').encode(), PASSWORD.encode()):
        return Response('Password required', 401, {'WWW-Authenticate': 'Basic realm="Rally route finder"'})


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


def save_worker_copy(run):
    """Save the worker's copy of a run, keeping any name given to it since
    the worker loaded it."""
    with save_lock:
        run['name'] = load_run(run['id']).get('name', '')
        save_run(run)


def all_runs():
    runs = []
    for name in os.listdir(RESULTS_DIR):
        if name.endswith('.json'):
            with open(os.path.join(RESULTS_DIR, name)) as f:
                runs.append(json.load(f))
    return sorted(runs, key=lambda run: run['created'], reverse=True)


def data_fingerprint():
    """Changes whenever the bonus or combo file does, so old results aren't
    reused for new data."""
    digest = hashlib.sha256()
    for path in (BONUS_CSV, COMBOS_CSV):
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
    for name, *_ in SWITCHES:
        settings[name] = form.get(name) == 'on'
    try:
        settings['start'] = planRoute.start_time(form.get('start', '').strip())
    except argparse.ArgumentTypeError as error:
        raise ValueError(f"Rally start: {error}")
    settings['must'] = ','.join(code.strip().upper() for code in form.get('must', '').split(',') if code.strip())
    return settings


def describe(settings):
    """A short line for the list of runs, e.g. '9.5 h, 46 MPH, 4 min stops, road x1.22'."""
    parts = [f"{settings['hours']:g} h", f"{settings['speed']:g} MPH", f"{settings['stop_minutes']:g} min stops",
             f"road ×{settings['road_factor']:g}"]
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
        parts.append(f"must visit {settings['must']}")
    parts += [text for name, text in SWITCHED_OFF.items() if not settings[name]]
    return ', '.join(parts)


def plan(run):
    """Run the planner for one saved run, and save the result or the error."""
    settings = run['settings']
    args = argparse.Namespace(first=settings.get('first'), must=settings.get('must'), gas_miles=settings['gas_miles'],
                              gas_minutes=settings['gas_minutes'], combos=COMBOS_CSV,
                              ignore_combos=not settings['use_combos'])
    started = time.monotonic()
    try:
        hq, bonuses = planRoute.load_bonuses(BONUS_CSV)
        slow_zones = [planRoute.ATLANTA_SLOW_ZONE] if settings['slow_zone'] else []
        planner = planRoute.Planner(hq, bonuses, settings['hours'], settings['speed'], settings['stop_minutes'],
                                    settings['road_factor'], settings['front_load'], slow_zones,
                                    settings['gas_miles'], settings['gas_minutes'], settings['start'],
                                    settings['use_hours'])
        # The planner stops with sys.exit on bad input, e.g. an unknown --must code
        planRoute.apply_first(planner, args)
        planRoute.apply_combos(planner, args)
        route = planner.solve(planRoute.START_WEIGHTS, 6, WORKERS)
    except SystemExit as stop:
        run.update(status='error', error=str(stop.code).removeprefix('ERROR: ').replace('--must', 'Must visit')
                   .replace('--first', 'First stops'))
        save_worker_copy(run)
        return
    except Exception as error:
        run.update(status='error', error=f"The planner failed: {error}")
        save_worker_copy(run)
        raise

    legs = list(planRoute.route_legs(planner, route))
    planRoute.write_gpx(planner, route, result_path(run['id'], 'gpx'))
    run.update(status='done', seconds=round(time.monotonic() - started),
               finished=datetime.now(timezone.utc).isoformat(timespec='seconds'),
               points=legs[-1].score, stops=len(route), miles=round(legs[-1].miles),
               hours=round(legs[-1].hours, 2),
               settings_lines=[f"{len(bonuses)} bonuses, {planRoute.describe_gas(args)}, "
                               f"{planRoute.describe_slow_zones(slow_zones)}, {planRoute.describe_first(planner)}",
                               planRoute.describe_hours(planner), planRoute.describe_combos(planner)],
               summary=planRoute.summary_lines(planner, route, legs),
               legs=[dict(code=leg.place['code'], state=leg.place['state'], points=leg.place['points'],
                          lat=leg.place['lat'], lon=leg.place['lon'], leg_miles=round(leg.leg_miles, 1),
                          miles=round(leg.miles, 1), leave=round(leg.hours, 2),
                          arrive=planRoute.time_of_day(planner, leg.arrive), score=leg.score,
                          notes=planRoute.leg_notes(planner, leg))
                     for leg in legs])
    save_worker_copy(run)


def worker():
    # The planner reports progress through planRoute.progress; show it on the
    # run's page instead of a terminal
    while True:
        run_id = jobs.get()
        planRoute.progress = lambda text, run_id=run_id: progress.__setitem__(run_id, text.strip())
        run = load_run(run_id)
        run['status'] = 'running'
        save_worker_copy(run)
        try:
            plan(run)
        except Exception:
            app.logger.exception(f"run {run_id} failed")
        finally:
            progress.pop(run_id, None)


# Runs waiting when the server last stopped go back in the queue
for waiting in sorted((run for run in all_runs() if run['status'] in ('queued', 'running')),
                      key=lambda run: run['created']):
    jobs.put(waiting['id'])
threading.Thread(target=worker, daemon=True).start()


@app.get('/')
def index():
    settings = DEFAULTS
    if request.args.get('from'):
        settings = DEFAULTS | load_run(request.args['from'])['settings']
    return render_template('index.html', numbers=NUMBERS, switches=SWITCHES, settings=settings,
                           runs=all_runs(), describe=describe, error=None,
                           has_data=os.path.exists(BONUS_CSV))


@app.post('/run')
def start_run():
    try:
        settings = read_form(request.form)
    except ValueError as error:
        return render_template('index.html', numbers=NUMBERS, switches=SWITCHES,
                               settings=DEFAULTS | request.form.to_dict()
                               | {name: request.form.get(name) == 'on' for name, *_ in SWITCHES},
                               runs=all_runs(), describe=describe,
                               error=str(error), has_data=os.path.exists(BONUS_CSV)), 400
    if not os.path.exists(BONUS_CSV):
        abort(503, "No bonus data on the server yet")
    key = json.dumps(settings, sort_keys=True) + data_fingerprint()
    run_id = hashlib.sha256(key.encode()).hexdigest()[:12]
    path = result_path(run_id)
    if os.path.exists(path):
        run = load_run(run_id)
        if run['status'] != 'error':
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
        return progress.get(run['id'], 'Starting')
    return ''


@app.get('/run/<run_id>')
def show_run(run_id):
    run = load_run(run_id)
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
                           bonuses=[dict(code=b['code'], lat=b['lat'], lon=b['lon'], points=b['points'])
                                    for b in bonuses])


@app.post('/run/<run_id>/name')
def rename_run(run_id):
    with save_lock:
        run = load_run(run_id)
        run['name'] = request.form.get('name', '').strip()[:60]
        save_run(run)
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
