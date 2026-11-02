# The web app (webapp/app.py) under PyPy, which runs the planner about 7x
# faster than regular Python
FROM pypy:3.11-7.3.20-slim

WORKDIR /app
COPY webapp/requirements.txt webapp/requirements.txt
RUN pip install --no-cache-dir -r webapp/requirements.txt
COPY planRoute.py checkRoute.py ./
COPY webapp webapp

# The bonus files are mounted at /data; runs are saved in /results
ENV DATA_DIR=/data RESULTS_DIR=/results
EXPOSE 8000
# One process, so there's one queue of runs; threads serve pages while a run goes
CMD ["gunicorn", "--chdir", "webapp", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:8000", "app:app"]
