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

def firstStopOptions(df_local):
    rv = df_local[df_local[0].str.contains('Rally')]
    print(f"[firstStopOptions] Length of rv: {len(rv)}")
    nextStops = rv.sort_values(by=4,  ascending=False, inplace=False)
    return(nextStops)
    
def searchNearest(df_local, bonus, path):
    while True:
        # print("point 100")
        # print(f"[searchNearest] len(df_local): {len(df_local)}")
        # print(f"[searchNearest] bonus: {bonus.strip()}")
        rv  = df_local[df_local[0].str.contains(bonus.strip())]
        nextStops = rv.sort_values(by=3, ascending=True, inplace=False)

        # print(f"[searchNearest] nextStops {nextStops.iloc[0]}")
        result = nextStops.iloc[0][1].strip() in path
        # print(f"Questions: Is {nextStops.iloc[0][1].strip()} in {path}?")
        # print(f"result {result}")
        if result == False:
            # print(f"[searchNearest] len(nextStops): {len(nextStops )}")
            return(nextStops)
        else:
            df_local = nextStops.drop(nextStops.index[0])

def evalNode(row, depth, path=[], dist=0, score=0):
    # print("[evalNode] point 10")
    # print(f"[evalNode] path {path}")
 
    ## limit check
    if(dist >= MAX_DISTANCE):
        return path, dist,score

    padding = '-'
    padding = padding.ljust(depth*2,">")
    # print(f"[evalNode]  {padding} Level: {depth}")
    # print(f"[evalNode] len(row): {len(row)}")

    # print("[evalNode] point 20")
    # row = row.iloc[0]
    # print(f"row: {row}")
    # print(f"[evalNode] type(row): {type(row)}")
    # print(f"[evalNode] row[0] {row[0]}")
    # print(f"row.iloc[0] {row.iloc[0]}")

    xyz = row[0]
    # print(f"[evalNode] type(xyz) {type(xyz)}")
    # print(f"[evalNode] xyz {xyz}")
    path.append(row[1].strip())
    dist = dist + int(row[2])
    score = score + int(row[3])

    # print(f"[evalNode] path {path}, distance {dist}, score {score}")
    # print(f"[evalNode] distance {dist}, score {score}")


    # lessrows = df_local.drop(df_local.index[0])
    nextStops = searchNearest(df, row[1], path)

    path, dist, score = evalNode(nextStops.iloc[0], depth + 1, path, dist, score)
    return path, dist, score

### Start here

path = []
for index, row in firstStopOptions(df).iterrows():
    result = evalNode(row, 1, path, 0, 0)
    if result is not None:
        path, dist, score = result
        print(f"[main] path {path}\n score {score} \n dist {dist}")
        path = []

