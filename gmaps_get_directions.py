import googlemaps
from datetime import datetime
import sys, csv
from itertools import combinations


def generateDetails(addr1, addr2):
    gmaps = googlemaps.Client(key='REDACTED_GOOGLE_KEY')

    # Request directions via public transit
    now = datetime.now()

    directions_result = gmaps.directions(addr1,addr2,
                                        departure_time=now)

    # 1. Load the JSON data into a Python dictionary
    data = directions_result[0]


    # --- Extraction of 'legs' (The Route Segments) ---
    route_legs = data.get("legs", [])
    print("\n====================================")
    print(f"       EXTRACTING {len(route_legs)} LEGS          ")
    print("====================================")

    # Iterate through the list of legs (in this case, there's only one)
    for i, leg in enumerate(route_legs):
        print(f"\n--- Leg {i+1} Summary ---")
        
        # Extract total distance and duration for the leg
        distance = leg.get("distance", {}).get("text", "N/A")
        duration = leg.get("duration", {}).get("text", "N/A")
        traffic_duration = leg.get("duration_in_traffic", {}).get("text", "N/A")
        
        # Extract start and end addresses
        start_addr = leg.get("start_address", "N/A")
        end_addr = leg.get("end_address", "N/A")
        
        print(f"  Start: {start_addr}")
        print(f"  End:   {end_addr}")
        print(f"  Distance: {distance}")
        print(f"  Duration: {duration}")
        print(f"  Duration in Traffic: {traffic_duration}")
        
with open(sys.argv[1]) as f:
    lines = [line.strip() for line in f if line.strip()]

print(f"--- Comparing {len(lines)} lines in '{sys.argv[1]}' ({len(list(combinations(lines, 2)))} unique pairs) ---\n")

comparison_count = 0

# Iterate through every unique pair of lines (line1, line2)
for line1, line2 in combinations(lines, 2):
    comparison_count += 1

    print(f"Comparison {comparison_count}:")
    # print(f"  Line A: '{line1}'")
    # print(f"  Line B: '{line2}'")

    bonus1 = line1.split(",")[0]
    bonus2 = line2.split(",")[0]
    latlon1 = line1.split(",")[1] + "," + line1.split(",")[2]
    latlon2 = line2.split(",")[1] + "," + line2.split(",")[2]
    
    print(f"{latlon1} vs {latlon2}")

    generateDetails(latlon1, latlon2)
    if(comparison_count > 4 ):
        sys.exit()

            