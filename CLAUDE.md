# Rally Route Finder

Plans the highest-scoring route for a one-day motorcycle bonus rally (SNAFU,
Georgia). README.md is the full manual: read the section you need instead of
the whole file (it is over 1,000 lines).

## Layout

- `extractDatafromGPX.py`: rally GPX + rally book -> `bonus-lat-lon-points.csv`,
  `bonus-combos.csv`, and two GPX files (Garmin, GPX Studio)
- `planRoute.py`: the planner (greedy insertion + drop/swap search), the
  confidence simulation, `--best-budget`, GPX/trip output
- `planRouteSearch.py`: quick mode (beam search); `planRouteExact.py`: CP-SAT
  exact solver (OR-Tools, CPython only, not in the web app)
- `buildRoadMiles.py`: road miles between every pair of bonuses from a local
  GraphHopper (route-camp's, port 8989) -> `bonus-road-miles.csv`, for
  `--road-miles` and the web app's Road miles switch
- `checkRoute.py`: checks a route with the Google Maps Routes API (billed)
- `webapp/`: Flask app (`app.py`, templates, static); runs under PyPy in Docker
- `docker-compose.yml`: `app` on port 80, optional `guest` site on 8000
  (`COMPOSE_PROFILES=guest`); HTTPS comes from a Cloudflare Tunnel

## Running and testing

- Python: `.venv/bin/python planRoute.py --quick ...` (Flask is not in .venv)
- Web app: `docker compose up -d --build`, then test in the container with
  `docker compose exec -T app python -` and Flask's test client
  (`sys.path.insert(0, 'webapp'); import app`); log in by posting the
  password to `/login`. Stale pages after a change: `docker compose build
  --no-cache`
- Put scratch files and experiment output in the session scratchpad, never
  in the project folder

## Rules

- Never read, print or commit `.env`
- Never write the Google API key to any file; use it only as an inline
  `GMAPS_API_KEY=` environment variable. Keep Google spending under $10;
  ask before any command that calls Google
- Rally data stays out of git: `*SNAFU*` folders, rally books, the generated
  bonus CSV/GPX files, `data/`, `scenarios-*/`
- Commit or push only when asked. `tools/make_booklet.py` is the owner's
  staged file: unstage it before committing and restage it after, so it
  never goes into a commit
- No force pushes or other destructive git operations without asking; don't
  delete untracked files without asking
- Saved web runs are keyed by a hash of their settings: keep existing
  setting names (e.g. `slow_zone`, `use_hours`) so saved runs keep their IDs
- Update README.md along with any change to options or behavior
