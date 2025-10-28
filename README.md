Directions:

1. ## Create combined  csv with bonus, lat, lon and points

    Use the Lat Lon from the GPX file (the other file may be wrong)

    `
    python extractDatafromGPX.py 2023\ SNAFU\ Bonus_Code-Lat-Long-Points.csv SNAFU\ 2023\ -\ FINAL.gpx
    `

2. ## Create a list of combinations

    Gets the bonus code from the provided csv file.

     Output is, `bonus1, bonus2, latlon2, latlon2, points at destination`

    `
    python generateCombinationsFile.py  bonus-lat-lon-points.csv  combos.csv
    `

3. ## Add the combos to a persistent queue

    This helps save $$$...puts the combinations on a local, perisistent. Now we can restart the process if it is interrupted... and not have to re-run against Google's API.

    `
    python enqueueCSV.py combos.csv
    `

4. ## Read from queue and query Google API, storing results in csv

    **NOTE: This costs about $300 to run!!!!**

    `
    python getDirections.py  segments.csv
    `

5. ## Search all segments for best route

    `
    python searchSegments.py segments.csv
    `


