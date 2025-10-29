#!/usr/bin/env python
import csv, os, sys,traceback
import pandas as pd

csv_file_path =  sys.argv[1]

# Read the CSV file into a pandas DataFrame
df = pd.read_csv(csv_file_path,  header=None)

# Read the bonus-lat-long-points.csv file into a pandas DataFrame 
# for looking up the state for each bonus
sf = pd.read_csv("bonus-lat-lon-points.csv",  header=None)

# 1609.34 Meters in Mile
# 9 hours * 65 miles = 585 miles
# = 941,466 meters
# MAX_DISTANCE = 941466
MAX_DISTANCE = 10000000
MAX_TIME = 40000

def firstStopOptions(df_local):
    rv = df_local[df_local[0].str.contains('Rally')]
    print(f"[firstStopOptions] Length of rv: {len(rv)}")
    # sys.exit(1)
    nextStops = rv.sort_values(by=3,  ascending=False, inplace=False)
    return(nextStops)
    
def searchHighScore(df_local, bonus, path):
    while True:
        rv  = df_local[df_local[0].str.contains(bonus.strip())]
        nextStops = rv.sort_values(by=2, ascending=False, inplace=False)
        inPathtf = nextStops.iloc[0][1].strip() in path
        isHQtf = 'Rally' in nextStops.iloc[0][1].strip()
        if inPathtf == False and isHQtf == False:
                return(nextStops)
        else:
            # print(f"[searchNeareset] path {path}")
            # # print(f"[searchNeareset] bonus {bonus}")
            # print(f"[searchNeareset] nextStops.iloc[0][1].strip()  {nextStops.iloc[0][1].strip() }")
            # print("---")
            # print(f"nextStops {nextStops}")
            df_local = nextStops.drop(nextStops.index[0])

def searchNearest(df_local, bonus, path):
    while True:
        rv  = df_local[df_local[0].str.contains(bonus.strip())]
        nextStops = rv.sort_values(by=3, ascending=True, inplace=False)
        inPathtf = nextStops.iloc[0][1].strip() in path
        isHQtf = 'Rally' in nextStops.iloc[0][1].strip()
        if inPathtf == False and isHQtf == False:
                return(nextStops)
        else:
            # print(f"[searchNeareset] path {path}")
            # # print(f"[searchNeareset] bonus {bonus}")
            # print(f"[searchNeareset] nextStops.iloc[0][1].strip()  {nextStops.iloc[0][1].strip() }")
            # print("---")
            # print(f"nextStops {nextStops}")
            df_local = nextStops.drop(nextStops.index[0])

def getState(bonus):
    row = sf[sf[0].str.contains(bonus.strip())]
    return row.iloc[0][4].strip()

def getDistAndTime(row):
        dist = int(row.iloc[0][2])
        time = int(row.iloc[0][3])
        return(dist, time)


def evalNode(row, depth, path=[], dist=0, time=0, score=0, states=[]):
    nextBonus = row[1].strip()
    lastBonus = ''
    distanceToHQlast = timeToHQlast = distanceToHQNext = timeToHQNext = 0
    if len(path) > 0:
        lastBonus = path[len(path)-1]
        toHQLast = df[ (df[1].str.contains('Rally') & df[0].str.contains(lastBonus)) ]
        rv = getDistAndTime(toHQLast)  
        if rv is not None: 
            distanceToHQlast, timeToHQlast = rv
    else:
        fromHQ = df[ (df[1].str.contains(nextBonus) & df[0].str.contains('Rally')) ]
        rv = getDistAndTime(fromHQ)  
        if rv is not None: 
            d, t = rv
            dist = d + dist
            time = t + time


    toHQNext = df[ (df[1].str.contains('Rally') & df[0].str.contains(nextBonus)) ]

    try:
        rv = getDistAndTime(toHQNext)  
        if rv is not None: 
            distanceToHQNext, timeToHQNext = rv      
    except Exception as e:
        print(f"nextBonus {nextBonus}")
        print(f"lastBonus {lastBonus}")
        sys.exit()
        return path, dist, time, score, states
    if( MAX_TIME - time) <= timeToHQNext:
        #print(f"CUTOFF Max Time ")
        # if (score * len(set(states)) > 13000):
        #     print("-----------")
        #     print(f"nextBonus (tested) {nextBonus}")
        #     print(f"lastBonus in path {lastBonus}") 
        #     print(f"Time remaining:{MAX_TIME - time}")
        #     print(f"timeToHQNext: {timeToHQNext}")
        #     print(f"timeToHQlast {timeToHQlast}")
        #     print(f"path {path}")
        #     print(f"states {states}")
        #     print(f"score {score * len(set(states))}")
        #     input()
        # path.append(row[1].strip())
        path.append(toHQNext.iloc[0][1])
        # states.append(getState(row[1].strip()))
        dist = dist + distanceToHQlast
        time = time + timeToHQlast
        return path, dist, time, score, states
    if( (MAX_DISTANCE - dist) <= distanceToHQNext):
        print(f"CUTOFF Return Distance")
        print(f"path: {path}")
        path.append(row[1].strip())
        path.append(toHQNext.iloc[0][1])
        states.append(getState(row[1].strip()))
        dist = dist + distanceToHQNext
        time = time + toHQNext.iloc[0][3]
        return path, dist, time, score, states

    padding = '-'
    padding = padding.ljust(depth*2,">")

    xyz = row[0]
    states.append(getState(row[1].strip()))
    path.append(row[1].strip())
    dist = dist + int(row[2])
    time = time + int(row[3])
    score = score + int(row[4])

    # print(f"accum time {time}")

    #nextStops = searchHighScore(df, row[1], path)
    nextStops = searchNearest(df, row[1], path)

    path, dist, time, score, states = evalNode(nextStops.iloc[0], depth + 1, path, dist, time, score, states)
    return path, dist, time, score, states


### Start here

max_score = 0
max_mscore = 0
best_distance = 0
best_time = 0
best_path = []
best_states = []
path = []
states = []
best_num_states = 0

for index, row in firstStopOptions(df).iterrows():
    result = evalNode(row, 1, path, 0, 0, 0, states )
    if result is not None:
        path, dist, time, score, states = result
        num_states = len(set(states))
        mscore = score * num_states
        # print("---")
        # print(f"[main] path {path}\n score {score} num_states {num_states} mscore {mscore} \n dist {dist} \n time {time} \n states {states}")
        if mscore > max_mscore:
            print("---")
            print(f"[main] path {path}\n score {score} num_states {num_states} mscore {mscore} \n dist {int(dist/1609.34)} \n time {time} \n states {states}")
            max_score = score
            max_mscore = mscore
            best_time = time
            best_distance = dist
            best_path  = path
            best_states = states
            best_num_states = num_states
            print(f"[BEST SCORE] \npath {best_path}\nstates {best_states} \n score {max_score} num_states {best_num_states} mscore {max_mscore}\n dist {best_distance/1609.4} \n time {int(best_time/60/60)} ")
            #input("press Enter to continue...")
        path = []
        states = []


print(f"[BEST SCORE] path {best_path}\n score {max_score} num_states {best_num_states} mscore {max_mscore}\n dist {best_distance/1609.34} \n time {best_time/60/60} \n states {best_states}")
print(f"Points per mile: {max_mscore / (best_distance/1609.34)}")
# print(len(set(best_states)))

