#!/usr/bin/env python
import sys
import xml.etree.ElementTree as ET
import pandas as pd

# sleep_time = os.environ.get('SLEEP_TIME', "1000")


csv_file_path =  sys.argv[1]

# Read the CSV file into a pandas DataFrame
# file has the points for each bonus, not in the GPX file
csvDataFrame = pd.read_csv(csv_file_path,  header=None)

# Exact-match lookup of points by bonus code
points_by_code = dict(zip(csvDataFrame[0].astype(str).str.strip(), csvDataFrame[3]))


#
# Got this from gemeni.. need to add the namespace 
#   for *.get() to work 
#

# Define the primary GPX namespace URI
GPX_NAMESPACE = "{http://www.topografix.com/GPX/1/1}"

# Define the Garmin extension namespace URIs (needed to find the State tag)
GPXX_NAMESPACE = "{http://www.garmin.com/xmlschemas/GpxExtensions/v3}"
WPTX1_NAMESPACE = "{http://www.garmin.com/xmlschemas/WaypointExtension/v1}"
    
# Define the full qualified tags for elements we want to find
WPT_TAG = GPX_NAMESPACE + "wpt"
NAME_TAG = GPX_NAMESPACE + "name"

# Define the State tags using their full namespaces
GPXX_STATE_TAG = GPXX_NAMESPACE + "State"
WPTX1_STATE_TAG = WPTX1_NAMESPACE + "State"

# Load GPX file with working lat-lons
tree = ET.parse(sys.argv[2])
root = tree.getroot()

def is_rally_hq(code):
    return 'Rally' in code

# Rally HQ is the start/finish of every route, so the GPX must have it
hq_names = [w.findtext(NAME_TAG, '').strip() for w in root.findall(WPT_TAG)]
if not any(is_rally_hq(name) for name in hq_names):
    sys.exit(f"ERROR: no 'Rally HQ' waypoint found in {sys.argv[2]}")

# Create merged file with lat-lon from GPX and bonus 
#   details from CSV file
with open('bonus-lat-lon-points.csv', 'w') as f:
    # Iterate through child elements
    for bonus in root.findall(WPT_TAG):
        lat = bonus.get('lat')
        lon = bonus.get('lon')
        name_element = bonus.find(NAME_TAG)
        code = (name_element.text or '').strip() if name_element is not None else ''
        state = "N/A"
        # Search recursively (using .//) for the State tag in the gpxx namespace
        state_element_gpxx = bonus.find(f".//{GPXX_STATE_TAG}")

        if state_element_gpxx is not None:
            state = state_element_gpxx.text
        else:
            # If not found in gpxx, try the wptx1 namespace
            state_element_wptx1 = bonus.find(f".//{WPTX1_STATE_TAG}")
            if state_element_wptx1 is not None:
                state = state_element_wptx1.text

        if is_rally_hq(code):
            # Rally HQ is the start/finish, not a bonus, so it's always worth
            # nothing, whatever the CSV says
            points = 0
        elif code in points_by_code:
            points = points_by_code[code]
        else:
            print(f"WARNING: no points found in {csv_file_path} for waypoint '{code}'", file=sys.stderr)
            points = "ERROR"
            code = code + " ERROR"

        print(f"{code}, {lat}, {lon},{points}, {state}")
        f.write(f"{code}, {lat}, {lon},{points}, {state}\n")
