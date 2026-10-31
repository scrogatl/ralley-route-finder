#!/usr/bin/env python
import re, sys
import xml.etree.ElementTree as ET
import pandas as pd

# sleep_time = os.environ.get('SLEEP_TIME', "1000")


csv_file_path =  sys.argv[1]

# Read the CSV file into a pandas DataFrame
# file has the points for each bonus, not in the GPX file
csvDataFrame = pd.read_csv(csv_file_path,  header=None)

# Exact-match lookup of points by bonus code
points_by_code = dict(zip(csvDataFrame[0].astype(str).str.strip(), csvDataFrame[3]))

# Optional third argument: the rally book PDF, for the hours each bonus is open
rally_book_path = sys.argv[3] if len(sys.argv) > 3 else None

# "Available: 24 hours" or "Available: 11:00 AM – 1:00 PM" in the rally book
AVAILABLE = re.compile(r"Available:\s*(?:(24\s*hours?)|(\d{1,2}:\d{2}\s*[AP]M)\s*[–-]\s*(\d{1,2}:\d{2}\s*[AP]M))",
                       re.IGNORECASE)


def clock_24(text):
    """'3:30 PM' as '15:30'."""
    hour, minute = map(int, re.match(r"(\d+):(\d+)", text).groups())
    if text.strip().upper().endswith('PM') and hour != 12:
        hour += 12
    if text.strip().upper().endswith('AM') and hour == 12:
        hour = 0
    return f"{hour:02}:{minute:02}"


def read_bonus_hours(pdf_path):
    """Return {code: (open, close)} from the rally book, as 24-hour 'HH:MM'
    strings, or None for a bonus available 24 hours. Each bonus's entry
    starts with a line beginning with its code, followed a few lines later
    by its "Available:" line."""
    import pypdf
    text = '\n'.join(page.extract_text() for page in pypdf.PdfReader(pdf_path).pages)
    hours, code = {}, None
    for line in text.splitlines():
        # Some code lines run on from the row of asterisks above them
        words = line.lstrip('* ').split()
        if words and words[0] in points_by_code:
            code = words[0]
        match = AVAILABLE.search(line)
        # A bonus's first "Available:" line is its own
        if match and code and code not in hours:
            hours[code] = None if match.group(1) else (clock_24(match.group(2)), clock_24(match.group(3)))
            code = None
    return hours


bonus_hours = read_bonus_hours(rally_book_path) if rally_book_path else None


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
CMT_TAG = GPX_NAMESPACE + "cmt"
DESC_TAG = GPX_NAMESPACE + "desc"
LINK_TAG = GPX_NAMESPACE + "link"
SYM_TAG = GPX_NAMESPACE + "sym"

# Each bonus's symbol is a Garmin number showing its points in hundreds
# (630 points shows 6; 900 or more shows 9), so it reads without relying on
# color. Color only backs it up: blue below HIGH_POINTS, red from there.
# No green, which is hard to tell from red with red-green color blindness.
HIGH_POINTS = 500
LOW_COLOR, HIGH_COLOR = "Blue", "Red"

# Copy of the GPX with each bonus's points in its description
POINTS_GPX = 'bonus-lat-lon-points.gpx'

# Define the State tags using their full namespaces
GPXX_STATE_TAG = GPXX_NAMESPACE + "State"
WPTX1_STATE_TAG = WPTX1_NAMESPACE + "State"

# Keep the GPX file's own namespace prefixes when writing it back out
for _, (prefix, uri) in ET.iterparse(sys.argv[2], events=['start-ns']):
    ET.register_namespace(prefix, uri)

# Load GPX file with working lat-lons
tree = ET.parse(sys.argv[2])
root = tree.getroot()

def is_rally_hq(code):
    return 'Rally' in code

def add_points_to_desc(bonus, points, hours=None):
    """Put the points at the front of the waypoint's description, e.g.
    "630 points - Abraham Baldwin Agricultural College", plus its hours if
    it isn't open all day, e.g. "960 points, open 11:00-13:00 - ..."."""
    if hours:
        points = f"{points} points, open {hours[0]}-{hours[1]}"
    else:
        points = f"{points} points"
    desc = bonus.find(DESC_TAG)
    if desc is None:
        # GPX wants desc right after name and cmt
        desc = ET.Element(DESC_TAG)
        before = bonus.find(CMT_TAG)
        if before is None:
            before = bonus.find(NAME_TAG)
        bonus.insert(list(bonus).index(before) + 1 if before is not None else 0, desc)
        # Same indentation as the line before it
        desc.tail = before.tail if before is not None else None
    desc.text = f"{points} - {desc.text.strip()}" if (desc.text or '').strip() else points

def set_symbol(bonus, points):
    """Use the Garmin number symbol for this many points."""
    points = int(points)
    symbol = f"Number {min(points // 100, 9)}, {HIGH_COLOR if points >= HIGH_POINTS else LOW_COLOR}"
    sym = bonus.find(SYM_TAG)
    if sym is None:
        # GPX wants sym after name, cmt, desc and any links
        sym = ET.Element(SYM_TAG)
        before = [e for e in bonus if e.tag in (NAME_TAG, CMT_TAG, DESC_TAG, LINK_TAG)][-1]
        bonus.insert(list(bonus).index(before) + 1, sym)
        sym.tail = before.tail
    sym.text = symbol

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
            if bonus_hours is not None and code not in bonus_hours:
                print(f"WARNING: no 'Available:' hours found in {rally_book_path} for '{code}'; "
                      f"assuming 24 hours", file=sys.stderr)
            hours = bonus_hours.get(code) if bonus_hours else None
            add_points_to_desc(bonus, points, hours)
            set_symbol(bonus, points)
            # Points in the name too, e.g. "ABAC 510", for apps that ignore
            # Garmin symbols (GPX Studio); only in the GPX copy, not the CSV
            name_element.text = f"{code} {points}"
        else:
            print(f"WARNING: no points found in {csv_file_path} for waypoint '{code}'", file=sys.stderr)
            points = "ERROR"
            code = code + " ERROR"

        row = f"{code}, {lat}, {lon},{points}, {state}"
        if bonus_hours is not None:
            # Opening and closing time, both blank if it's open 24 hours
            hours = None if is_rally_hq(code) else bonus_hours.get(code)
            row += f", {hours[0]}, {hours[1]}" if hours else ", , "
        print(row)
        f.write(row + "\n")

tree.write(POINTS_GPX, encoding='utf-8', xml_declaration=True)
print(f"GPX with points in each name and description written to {POINTS_GPX}; each bonus's symbol is its points "
      f"in hundreds (9 = 900 or more), {LOW_COLOR.lower()} under {HIGH_POINTS} points, "
      f"{HIGH_COLOR.lower()} from {HIGH_POINTS}", file=sys.stderr)
