#!/usr/bin/env python
import csv, os, sys,traceback
import pandas as pd

csv_file_path =  sys.argv[1]

# Read the CSV file into a pandas DataFrame
df = pd.read_csv(csv_file_path,  header=None)

# 1609.34 Meters in Mile
# 9 hours * 65 miles = 585 miles
# = 941,466 meters
MAX_DISTANCE = 941466
MAX_TIME = 32400

def firstStopOptions(df_local):
    rv = df_local[df_local[0].str.contains('Rally')]
    print(f"[firstStopOptions] Length of rv: {len(rv)}")
    nextStops = rv.sort_values(by=4,  ascending=False, inplace=False)
    return(nextStops)
    
def searchNearest(df_local, bonus, path):
    while True:
        rv  = df_local[df_local[0].str.contains(bonus.strip())]
        nextStops = rv.sort_values(by=3, ascending=True, inplace=False)
        result = nextStops.iloc[0][1].strip() in path
        if result == False:
            return(nextStops)
        else:
            df_local = nextStops.drop(nextStops.index[0])

def evalNode(row, depth, path=[], dist=0, time=0, score=0):
    toHQ = df[ (df[1].str.contains('Rally') & df[0].str.contains(row[1].strip())) ]
    distanceToHQ = toHQ.iloc[0][2]
    if( MAX_TIME - time) <= toHQ.iloc[0][3]:
        print(f"CUTOFF Max Time ")
        path.append(toHQ.iloc[0][1])
        dist = dist + distanceToHQ
        time = time + toHQ.iloc[0][3]
        return path, dist, time, score
    if( (MAX_DISTANCE - dist) <= distanceToHQ):
        print(f"CUTOFF Return Distance")
        path.append(toHQ.iloc[0][1])
        dist = dist + distanceToHQ
        time = time + toHQ.iloc[0][3]
        return path, dist, time, score


    padding = '-'
    padding = padding.ljust(depth*2,">")

    xyz = row[0]
    path.append(row[1].strip())
    dist = dist + int(row[2])
    time = time + int(row[3])
    score = score + int(row[4])

    nextStops = searchNearest(df, row[1], path)

    path, dist, time, score = evalNode(nextStops.iloc[0], depth + 1, path, dist, time, score)
    return path, dist, time, score

### Start here

max_score = 0
best_distance = 0
best_time = 0
best_path = []
path = []
for index, row in firstStopOptions(df).iterrows():
    result = evalNode(row, 1, path, 0, 0, 0)
    if result is not None:
        path, dist, time, score = result
        print(f"[main] path {path}\n score {score} \n dist {dist} \n time {time}")
        path = []
        if score > max_score:
            max_score = score
            best_time = time
            best_distance = dist
            best_path  = path

print(f"[BEST SCORE] path {best_path}\n score {max_score} \n dist {best_distance} \n time {best_time}")

