#!/usr/bin/env python
"""
Combine the rally's bonus files into the files the planners read.

Takes each bonus's location from the rally's GPX file (the CSV's lat/lon may
be wrong) and its points from the rally's bonus CSV, and writes, in the
current directory, overwriting any earlier ones:

  bonus-lat-lon-points.csv  code, lat, lon, points, state, and with the rally
                            book, the hours each bonus is open
  bonus-combos.csv          with the rally book only: each combo's code,
                            points and the bonuses it needs
  bonus-lat-lon-points.gpx  the GPX with each bonus's points (and hours and
                            combos) in its name and description, for viewing
                            in BaseCamp or on a GPS, with Garmin number symbols
  bonus-lat-lon-points-gpxstudio.gpx
                            the same, with symbols GPX Studio shows instead

Without the rally book, the CSV has no hours and bonus-combos.csv isn't
written (an old one is left as it was). Check the warnings: a bonus with no
points in the CSV, or no hours in the rally book, is flagged.

    python extractDatafromGPX.py "SNAFU_2026/2026 SNAFU Bonus_Code-Lat-Long-Points_CSV - Final - 26 Oct 2026.csv" \\
        "SNAFU_2026/SNAFU 2026 - MASTER cao 11 Aug 26.gpx" "SNAFU_2026/2026 SNAFU Rally Book - Final 27 Oct 26.pdf"
"""
import argparse, os, re, sys
import xml.etree.ElementTree as ET
import pandas as pd

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('points_csv',
                    help="the rally's bonus CSV: code, lat, lon, points per row (only the code and points are used; "
                         "UTF-8 or Windows encoding)")
parser.add_argument('gpx_file', help="the rally's GPX file of bonus waypoints, including Rally HQ")
parser.add_argument('rally_book', nargs='?',
                    help="optional: the rally book PDF, for each bonus's opening hours and the combo bonuses")
args = parser.parse_args()
for path in filter(None, (args.points_csv, args.gpx_file, args.rally_book)):
    if not os.path.isfile(path):
        sys.exit(f"ERROR: no such file: {path}")
csv_file_path, gpx_file_path, rally_book_path = args.points_csv, args.gpx_file, args.rally_book

# Read the CSV file into a pandas DataFrame
# file has the points for each bonus, not in the GPX file
csvDataFrame = None
# Saved from Excel it may be in Windows encoding, not UTF-8 (the final 2026
# file has ° in its coordinates); latin-1 reads any bytes, so it's last
for encoding in ('utf-8', 'cp1252', 'latin-1'):
    try:
        csvDataFrame = pd.read_csv(csv_file_path, header=None, encoding=encoding)
        break
    except UnicodeDecodeError:
        continue

# Exact-match lookup of points by bonus code
points_by_code = dict(zip(csvDataFrame[0].astype(str).str.strip(), csvDataFrame[3]))

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


def read_combos(pdf_path):
    """Return [(code, points, [member codes])] from the rally book's
    COMBINATION BONUSES section. Each combo's entry is a line starting with
    its code, then "Points: N", then "Successfully claim the bonuses: A, B,
    C", which may wrap onto the next lines."""
    import pypdf
    text = '\n'.join(page.extract_text() for page in pypdf.PdfReader(pdf_path).pages)
    combos, current, collecting, started = [], None, False, False
    for line in text.splitlines():
        if 'COMBINATION BONUSES' in line and not line.strip().startswith('COMBINATION BONUSES –'):
            # The section heading, not the rules paragraph that describes combos
            started = True
            continue
        if not started:
            continue
        stripped = line.lstrip('* ').strip()
        if collecting:
            members = [word for word in re.split(r'[\s,]+', stripped) if word in points_by_code]
            if members:
                current[2].extend(members)
                continue
            collecting = False
        words = stripped.split()
        # A new combo starts with its code, once the one before has its bonuses
        if (words and re.fullmatch(r'[A-Z0-9]{2,}', words[0]) and words[0] not in points_by_code
                and (current is None or current[2])):
            current = [words[0], None, []]
            combos.append(current)
            continue
        if current is None:
            continue
        points = re.search(r'Points:\s*(\d+)', line)
        if points and current[1] is None:
            current[1] = int(points.group(1))
        claim = re.search(r'Successfully claim the bonuses:\s*(.*)', line)
        if claim:
            current[2].extend(word for word in re.split(r'[\s,]+', claim.group(1)) if word)
            collecting = True
    for code, points, members in combos:
        unknown = [m for m in members if m not in points_by_code]
        if points is None or not members or unknown:
            print(f"WARNING: combo '{code}' in {pdf_path}: "
                  + (f"no points found; " if points is None else '')
                  + (f"no bonuses found; " if not members else '')
                  + (f"unknown bonuses {', '.join(unknown)}; " if unknown else '')
                  + "check bonus-combos.csv", file=sys.stderr)
    return combos


bonus_hours = read_bonus_hours(rally_book_path) if rally_book_path else None
combos = read_combos(rally_book_path) if rally_book_path else []
# The combos each bonus is part of, for its GPX description
combos_of = {}
for combo_code, _, members in combos:
    for member in members:
        combos_of.setdefault(member, []).append(combo_code)

# Combos go in their own file: code, points, then the bonuses it needs
COMBOS_CSV = 'bonus-combos.csv'


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

# The same for GPX Studio, which ignores Garmin's number symbols and shows
# only its own short list (an icon for each of about 40 Garmin names), so
# there each bonus gets an icon for its points: (lowest points, symbol)
GPX_STUDIO_GPX = 'bonus-lat-lon-points-gpxstudio.gpx'
GPX_STUDIO_SYMBOLS = [(800, 'Summit'), (500, 'Alert'), (300, 'Binoculars'), (0, 'Information')]
GPX_STUDIO_HQ = 'House'

# Define the State tags using their full namespaces
GPXX_STATE_TAG = GPXX_NAMESPACE + "State"
WPTX1_STATE_TAG = WPTX1_NAMESPACE + "State"

# Keep the GPX file's own namespace prefixes when writing it back out
for _, (prefix, uri) in ET.iterparse(gpx_file_path, events=['start-ns']):
    ET.register_namespace(prefix, uri)

# Load GPX file with working lat-lons
tree = ET.parse(gpx_file_path)
root = tree.getroot()

def is_rally_hq(code):
    return 'Rally' in code

def add_points_to_desc(bonus, points, hours=None, combo_codes=()):
    """Put the points at the front of the waypoint's description, e.g.
    "630 points - Abraham Baldwin Agricultural College", plus its hours if
    it isn't open all day and any combos it's part of, e.g.
    "960 points, open 11:00-13:00, EAGLE combo - ..."."""
    points = f"{points} points"
    if hours:
        points += f", open {hours[0]}-{hours[1]}"
    for combo_code in combo_codes:
        points += f", {combo_code} combo"
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

def garmin_symbol(points):
    """The Garmin number symbol for this many points."""
    points = int(points)
    return f"Number {min(points // 100, 9)}, {HIGH_COLOR if points >= HIGH_POINTS else LOW_COLOR}"

def gpx_studio_symbol(points):
    return next(symbol for lowest, symbol in GPX_STUDIO_SYMBOLS if int(points) >= lowest)

def set_symbol(bonus, symbol):
    """Set the waypoint's symbol; returns its sym element."""
    sym = bonus.find(SYM_TAG)
    if sym is None:
        # GPX wants sym after name, cmt, desc and any links
        sym = ET.Element(SYM_TAG)
        before = [e for e in bonus if e.tag in (NAME_TAG, CMT_TAG, DESC_TAG, LINK_TAG)][-1]
        bonus.insert(list(bonus).index(before) + 1, sym)
        sym.tail = before.tail
    sym.text = symbol
    return sym

# Rally HQ is the start/finish of every route, so the GPX must have it
hq_names = [w.findtext(NAME_TAG, '').strip() for w in root.findall(WPT_TAG)]
if not any(is_rally_hq(name) for name in hq_names):
    sys.exit(f"ERROR: no 'Rally HQ' waypoint found in {gpx_file_path}")

# Each waypoint's sym element and its symbol for GPX Studio, swapped in
# after the Garmin copy is written
gpx_studio_syms = []

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
            gpx_studio_syms.append((set_symbol(bonus, bonus.findtext(SYM_TAG) or GPX_STUDIO_HQ), GPX_STUDIO_HQ))
        elif code in points_by_code:
            points = points_by_code[code]
            if bonus_hours is not None and code not in bonus_hours:
                print(f"WARNING: no 'Available:' hours found in {rally_book_path} for '{code}'; "
                      f"assuming 24 hours", file=sys.stderr)
            hours = bonus_hours.get(code) if bonus_hours else None
            add_points_to_desc(bonus, points, hours, combos_of.get(code, ()))
            gpx_studio_syms.append((set_symbol(bonus, garmin_symbol(points)), gpx_studio_symbol(points)))
            # Points in the name too, e.g. "ABAC 510", for apps that ignore
            # Garmin symbols; only in the GPX copies, not the CSV
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

if rally_book_path:
    with open(COMBOS_CSV, 'w') as f:
        for combo_code, combo_points, members in combos:
            f.write(f"{combo_code}, {combo_points}, {' '.join(members)}\n")
    print(f"{len(combos)} combos written to {COMBOS_CSV}: "
          + ", ".join(f"{c} {p} ({' '.join(m)})" for c, p, m in combos), file=sys.stderr)

tree.write(POINTS_GPX, encoding='utf-8', xml_declaration=True)
print(f"GPX with points in each name and description written to {POINTS_GPX}; each bonus's symbol is its points "
      f"in hundreds (9 = 900 or more), {LOW_COLOR.lower()} under {HIGH_POINTS} points, "
      f"{HIGH_COLOR.lower()} from {HIGH_POINTS}", file=sys.stderr)

for sym, symbol in gpx_studio_syms:
    sym.text = symbol
tree.write(GPX_STUDIO_GPX, encoding='utf-8', xml_declaration=True)
print(f"The same for GPX Studio written to {GPX_STUDIO_GPX}; each bonus's symbol is "
      + ", ".join(f"{symbol} from {lowest}" if lowest else f"{symbol} below {GPX_STUDIO_SYMBOLS[-2][0]}"
                  for lowest, symbol in GPX_STUDIO_SYMBOLS)
      + f" points, Rally HQ {GPX_STUDIO_HQ}", file=sys.stderr)
