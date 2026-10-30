import googlemaps
from datetime import datetime
import json,sys,os

gmaps = googlemaps.Client(key=os.environ['GMAPS_API_KEY'])

# Geocoding an address
# geocode_result = gmaps.geocode('1600 Amphitheatre Parkway, Mountain View, CA')

# Look up an address with reverse geocoding
# reverse_geocode_result = gmaps.reverse_geocode((40.714224, -73.961452))

# Request directions via public transit
now = datetime.now()
directions_result = gmaps.directions("32.610320001840591, -85.48080001026392",
                                     "33.666510209441185, -84.018228147178888",
                                     departure_time=now)

# directions_result = gmaps.directions("Roswell, Georgia",
#                                      "Suches, GA",
#                                      departure_time=now)


print(json.dumps(directions_result))
print(type(directions_result))
print(type(directions_result[0]))
# print(len(directions_result))
# print(json.dumps(directions_result[0]))
#print(type(directions_result[0]))
#print(directions_result[0].keys())
#print(type(directions_result[0]["legs"]))
#for item in directions_result[0]["legs"]:
#    print(type(item))
#print(directions_result[0]["legs"][0].keys())

# sys.exit()


# Validate an address with address validation
#addressvalidation_result =  gmaps.addressvalidation(['1600 Amphitheatre Pk'], 
#                                                     regionCode='US',
#                                                     locality='Mountain View', 
#                                                     enableUspsCass=True)
#
#print(json.dumps(addressvalidation_result))


# 1. Load the JSON data into a Python dictionary
#data = directions_result
#data = json.loads(directions_result[0])
data = directions_result[0]

# --- Extraction of Top-Level Values ---
print("====================================")
print("       TOP-LEVEL ROUTE DATA         ")
print("====================================")
print(f"Copyrights: {data.get('copyrights', 'N/A')}")

# --- Extraction of 'legs' (The Route Segments) ---
route_legs = data.get("legs", [])
print("\n====================================")
print(f"       EXTRACTING {len(route_legs)} LEGS          ")
print("====================================")

# Iterate through the list of legs (in this case, there's only one)
for i, leg in enumerate(route_legs):
    print(f"\n--- Leg {i+1} Summary ---")
    
    # Extract total distance and duration for the leg
    distance = leg.get("distance", {}).get("value", "N/A")
    duration = leg.get("duration", {}).get("value", "N/A")
    traffic_duration = leg.get("duration_in_traffic", {}).get("text", "N/A")
    
    # Extract start and end addresses
    start_addr = leg.get("start_address", "N/A")
    end_addr = leg.get("end_address", "N/A")
    
    print(f"  Start: {start_addr}")
    print(f"  End:   {end_addr}")
    print(f"  Distance: {distance}")
    print(f"  Duration: {duration}")
    print(f"  Duration in Traffic: {traffic_duration}")
    
    # --- Extraction of 'steps' (The Individual Directions) ---
    steps = leg.get("steps", [])
    print(f"\n  --- Leg {i+1} Detailed Steps ({len(steps)} total) ---")
    
    # Iterate through the list of steps
    for j, step in enumerate(steps):
        # Clean up the HTML instructions for display
        instructions = step.get("html_instructions", "N/A").replace("<b>", "**").replace("</b>", "**")
        step_distance = step.get("distance", {}).get("text", "N/A")
        step_maneuver = step.get("maneuver", "N/A")

        print(f"  Step {j+1}: {instructions}")
        print(f"    - Distance: {step_distance}")
        if step_maneuver != "N/A":
            print(f"    - Maneuver: {step_maneuver}")
