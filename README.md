Directions:

### Use the Lat Lon from the GPX file (the other file may be wrong)

This will create a csv with the bonus, lat, lon and points

`python extractDatafromGPX.py 2023\ SNAFU\ Bonus_Code-Lat-Long-Points.csv SNAFU\ 2023\ -\ FINAL.gpx`

### Create a list of combinations
This will create a csv of all combinations. Output is, `bonus1, bonus2, latlon2, latlon2, points at destination`

`python extractDatafromGPX.py 2023\ SNAFU\ Bonus_Code-Lat-Long-Points.csv SNAFU\ 2023\ -\ FINAL.gpx`

### Enqueue the combos

This helps save $$$...puts the combinations on a local, perisistent. Now we can restart the process if it is interrupted... and not have to re-run against Google's API.

`python enqueueCSV.py combos.csv`


