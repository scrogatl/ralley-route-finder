import googlemaps
from datetime import datetime
import sys, csv, os
from itertools import combinations


def generateDetails(addr1, addr2):
    gmaps = googlemaps.Client(key=os.environ['GMAPS_API_KEY'])

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
        
        # Extract start and end addresses
        start_addr = leg.get("start_address", "N/A")
        end_addr = leg.get("end_address", "N/A")
        
#        print(f"  Start: {start_addr}")
#        print(f"  End:   {end_addr}")
#        print(f"  Distance: {distance}")
#        print(f"  Duration: {duration}")
#        print(f"  Duration in Traffic: {traffic_duration}")
#
        return [distance, duration]
        
with open(sys.argv[1]) as f:
    lines = [line.strip() for line in f if line.strip()]

print(f"--- Comparing {len(lines)} lines in '{sys.argv[1]}' ({len(list(combinations(lines, 2)))} unique pairs) ---\n")
sys.exit()

comparison_count = 0

with open(sys.argv[2], 'w') as f:
    f.write("start, end, distance, duration, points-at-dest\n")
    # Iterate through every unique pair of lines (line1, line2)

    for line1, line2 in combinations(lines, 2):
        comparison_count += 1

        bonus1 = line1.split(",")[0]
        bonus2 = line2.split(",")[0]
        latlon1 = line1.split(",")[1] + "," + line1.split(",")[2]
        latlon2 = line2.split(",")[1] + "," + line2.split(",")[2]
        
        results = generateDetails(latlon1, latlon2)
        
        print(f"Comparison {comparison_count}:")
        print(f"  Line A: '{line1}'")
        print(f"  Line B: '{line2}'")
        print(f"     {bonus1}, {bonus2}, {results[0]}, {results[1]}, {line2.split(",")[3]}\n")


        f.write(f"{bonus1}, {bonus2}, {results[0]}, {results[1]}, {line2.split(",")[3]}\n")
        
        if(comparison_count % 25):
            f.flush()

            
