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
    APP_PASSWORD     required; the password for the whole site (any user name)
    DATA_DIR         folder with bonus-lat-lon-points.csv and bonus-combos.csv
                     from extractDatafromGPX.py (default: the repo folder)
    RESULTS_DIR      where runs are saved (default: DATA_DIR/web-scenarios)
    PLANNER_WORKERS  CPU cores per run (default: all)
    GOOGLE_CHECK     'on' adds a "Check with Google" button to finished routes;
                     leave it off on a public site, since every check is billed
                     to your Google account (default: off)
    GMAPS_API_KEY    the Google Maps API key, needed when GOOGLE_CHECK is on
    RALLY_TZ         time zone for Google departure times (default America/New_York)

    APP_PASSWORD=secret flask --app webapp/app.py run    # to try it locally
"""
import argparse, glob, hashlib, hmac, json, math, os, queue, sys, threading, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Flask, Response, abort, redirect, render_template, request, send_file, url_for

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import planRoute, planRouteSearch

PASSWORD = os.environ.get('APP_PASSWORD') or sys.exit("ERROR: set APP_PASSWORD to the site's password")
DATA_DIR = os.environ.get('DATA_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
RESULTS_DIR = os.environ.get('RESULTS_DIR') or os.path.join(DATA_DIR, 'web-scenarios')
BONUS_CSV = os.path.join(DATA_DIR, 'bonus-lat-lon-points.csv')
COMBOS_CSV = os.path.join(DATA_DIR, 'bonus-combos.csv')
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
    ('only', 'Only the must-visit bonuses', False, 'route just those, in the quickest order, adding nothing else'),
    ('quick', 'Quick mode', False, 'beam search: about 4x faster and as good on the 2026 bonuses, but it may '
                                   'miss a better route; no front-load'),
]
# How the list of runs describes a switch that's off (only and quick, off by
# default, are described when on)
SWITCHED_OFF = {'slow_zone': 'no Atlanta slow zone', 'use_hours': 'bonus hours ignored', 'use_combos': 'no combos'}
DEFAULTS = {name: default for name, _, default, *_ in NUMBERS} | {name: on for name, _, on, _ in SWITCHES} | {
    'must': '', 'start': planRoute.RALLY_START}

app = Flask(__name__)


@app.context_processor
def google_setting():
    return {'google_enabled': GOOGLE_CHECK}

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
# One Google check at a time, so a double click can't pay for the same check twice
check_lock = threading.Lock()


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
    if settings['only'] and not settings['must']:
        raise ValueError("Only the must-visit bonuses: list the bonuses in Must visit")
    if settings['quick'] and settings['front_load']:
        raise ValueError("Quick mode: set Front-load to 0, since quick mode doesn't support it")
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
    if settings.get('only'):
        parts.append('only those')
    if settings.get('quick'):
        parts.append('quick mode')
    return ', '.join(parts)


def plan(run):
    """Run the planner for one saved run, and save the result or the error."""
    settings = run['settings']
    args = argparse.Namespace(first=settings.get('first'), must=settings.get('must'), only=settings.get('only'), gas_miles=settings['gas_miles'],
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
        if settings.get('quick'):
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
                               planRoute.describe_hours(planner), planRoute.describe_combos(planner)]
                              + (["Quick mode: beam search (width 2000, branch 12), then planRoute.py's "
                                  "drop-and-reinsert search"] if settings.get('quick') else []),
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
                           bonuses=[dict(code=b['code'], lat=b['lat'], lon=b['lon'], points=b['points'])
                                    for b in bonuses]), status


def google_check(run, depart, check_id):
    """Check a finished run's route with the Google Maps Routes API, as
    checkRoute.py does, and return the result to save with the run. Without
    depart it's one request with no traffic; with depart (a datetime), one
    request per leg with Google's traffic forecast. Exits (SystemExit) with a
    message if Google refuses."""
    settings = run['settings']
    places = [dict(code=leg['code'], lat=leg['lat'], lon=leg['lon'], points=leg['points'], state=leg['state'])
              for leg in run['legs']]
    start = f"{depart:%H:%M}" if depart else settings['start']
    windows = checkRoute.bonus_windows(BONUS_CSV, start) if settings['use_hours'] else {}
    combos = planRoute.load_combos(COMBOS_CSV) if settings['use_combos'] else []
    stop_hours, gas_hours = settings['stop_minutes'] / 60, settings['gas_minutes'] / 60
    if depart:
        legs, polylines = checkRoute.fetch_with_traffic(GMAPS_API_KEY, places, depart, stop_hours,
                                                        settings['gas_miles'], gas_hours, windows)
        source = f"with traffic, leaving {depart:%a %b} {depart.day} {depart:%H:%M}"
        requests_made = len(places) - 1
    else:
        legs, polylines = checkRoute.fetch_batched(GMAPS_API_KEY, places)
        source = "no traffic"
        requests_made = math.ceil((len(places) - 1) / (checkRoute.MAX_WAYPOINTS + 1))
    rows = list(checkRoute.timeline(places, legs, stop_hours, settings['gas_miles'], gas_hours, windows, combos))
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
                                                 settings['gas_miles'], time_of_day),
                rows=[dict(code=row.place['code'], state=row.place['state'], points=row.place['points'],
                           line_miles=round(planRoute.haversine_miles(rows[n - 1].place, row.place), 1) if n else 0,
                           road_miles=round(row.leg_miles, 1), miles=round(row.miles, 1),
                           drive=round(row.leg_hours * 60), arrive=time_of_day(row.arrive), leave=round(row.leave, 2),
                           score=row.score, missed=row.missed, notes=checkRoute.row_notes(row, windows))
                      for n, row in enumerate(rows)],
                # Google's roads for the map, to about 1 m
                track=[[round(lat, 5), round(lon, 5)] for polyline in polylines
                       for lat, lon in checkRoute.decode_polyline(polyline)])


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
    check_id = f"{depart:%Y%m%d%H%M}" if depart else 'notraffic'
    with check_lock:
        # Checked before? Show that one rather than paying Google again
        if check_id not in [check['id'] for check in load_run(run_id).get('checks', [])]:
            try:
                check = google_check(run, depart, check_id)
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
