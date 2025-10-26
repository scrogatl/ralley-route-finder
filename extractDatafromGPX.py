#!/usr/bin/env python
import csv, os, sys,traceback
import xml.etree.ElementTree as ET
import pandas as pd

# sleep_time = os.environ.get('SLEEP_TIME', "1000")


csv_file_path =  sys.argv[1]

# Read the CSV file into a pandas DataFrame
csvDataFrame = pd.read_csv(csv_file_path,  header=None)
# print(df)
# print(csvDataFrame[0][0])
# codes = csvDataFrame[0]
# print(codes)
# df = csvDataFrame[csvDataFrame[0].str.contains('ASHF')]
# print(df)
points = csvDataFrame[csvDataFrame[0].str.contains('RAVE')].iat[0,3]
print(f"Points: {points}")
# sys.exit()


# print(f"Root element tag: {root.tag}")
# print(f"Root element attrib: {root.attrib}")
# sys.exit()
# x = 1
# for element in root.iter():
#     print(element.tag, element.attrib)
#     # print(element.find('wpt'))
#     print("===============")
#     x = x + 1
#     if(x > 50 ): 
#         sys.exit('0')


# Define the primary GPX namespace URI
GPX_NAMESPACE = "{http://www.topografix.com/GPX/1/1}"
    
# Define the full qualified tags for elements we want to find
WPT_TAG = GPX_NAMESPACE + "wpt"
NAME_TAG = GPX_NAMESPACE + "name"
TYPE_TAG = GPX_NAMESPACE + "type"

tree = ET.parse(sys.argv[2])
root = tree.getroot()

with open('bonus-lat-long-ponts.csv', 'w') as f:
    # Iterate through child elements
    for bonus in root.findall(WPT_TAG):
        lat = lon = code = points = ''
        try:
            lat = bonus.get('lat')
            lon = bonus.get('lon')
            code = bonus.find(NAME_TAG).text
            points = csvDataFrame[csvDataFrame[0].str.contains(code)].iat[0,3]
        except Exception as e:
            # traceback.print_exc()
            points = "ERROR"
            code = code + " ERROR"


        # print(f"\nBonus: {code}")
        # print(f"Lat: {lat}")
        # print(f"Lon: {lon}")
        # print(f"Points: {points}")
        print(f"{code}, {lat}, {lon},{points}")
        # print("-----")
        f.write(f"{code}, {lat}, {lon},{points}\n")