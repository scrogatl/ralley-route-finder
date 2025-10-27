import googlemaps
import sys, csv
from persistqueue import Queue
from datetime import datetime



q = Queue("path_to_queue")

print(f"qsize: {q.qsize()}")

input()


gmaps = googlemaps.Client(key='REDACTED_GOOGLE_KEY')

def generateDetails(addr1, addr2):

    # Request directions via public transit
    now = datetime.now()

    directions_result = gmaps.directions(addr1,addr2,
                                        departure_time=now)

    # 1. Load the JSON data into a Python dictionary
    data = directions_result[0]

    # --- Extraction of 'legs' (The Route Segments) ---
    route_legs = data.get("legs", [])

    # Iterate through the list of legs (in this case, there's only one)
    for i, leg in enumerate(route_legs):
        # Extract total distance and duration for the leg
        distance = leg.get("distance", {}).get("value", "N/A")
        duration = leg.get("duration", {}).get("value", "N/A")
        traffic_duration = leg.get("duration_in_traffic", {}).get("text", "N/A")
        
        return [distance, duration]

with open(sys.argv[1], 'a') as f:
    while q.qsize() > 0:
        line = q.get()
        # print(f"Retrieved: {line}")
        bonus1 = line.split(",")[0]
        bonus2 = line.split(",")[1]
        latlon1 = line.split(",")[2] + "," + line.split(",")[3]
        latlon2 = line.split(",")[4] + "," + line.split(",")[5]
        points = line.split(",")[6]
        print(f"{bonus1}, {bonus2}, {latlon1}, {latlon2}, {points} ")
        results = generateDetails(latlon1, latlon2)
        print(f"{bonus1}, {bonus2}, {results[0]}, {results[1]}, {points}\n")        
        f.write(f"{bonus1}, {bonus2}, {results[0]}, {results[1]}, {points}\n")
        f.flush()
        q.task_done()



print(f"qsize: {q.qsize()}")
