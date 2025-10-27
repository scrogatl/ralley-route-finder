import googlemaps
from datetime import datetime
import sys, csv
from itertools import permutations
        
with open(sys.argv[1]) as f:
    lines = [line.strip() for line in f if line.strip()]

print(f"--- Comparing {len(lines)} lines in '{sys.argv[1]}' ({len(list(permutations(lines, 2)))} unique pairs) ---\n")

comparison_count = 0

with open(sys.argv[2], 'w') as f:
    # Iterate through every unique pair of lines (line1, line2)

    for line1, line2 in permutations(lines, 2):
        comparison_count += 1

        bonus1 = line1.split(",")[0]
        bonus2 = line2.split(",")[0]
        latlon1 = line1.split(",")[1] + "," + line1.split(",")[2]
        latlon2 = line2.split(",")[1] + "," + line2.split(",")[2]
        
        # results = generateDetails(latlon1, latlon2)
        
        print(f"Comparison {comparison_count}:")
        print(f"  Line A: '{line1}'")
        print(f"  Line B: '{line2}'")
        print(f"  {bonus1}, {bonus2}, {latlon1}, {latlon2} ,{line2.split(",")[3]}\n")

        f.write(f"  {bonus1}, {bonus2}, {latlon1}, {latlon2} ,{line2.split(",")[3]}\n")

        if(comparison_count % 25):
            f.flush()

print(f"Generated {comparison_count} permutations")