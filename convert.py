#!/usr/bin/pyhon
# coding=utf8

"""
Converting Degrees, Minutes, Seconds formatted coordinate strings to decimal. 

Formula:
DEC = (DEG + (MIN * 1/60) + (SEC * 1/60 * 1/60))

Assumes S/W are negative. 
"""

import re
import sys

def dms2dec(dms_str):
    """Return decimal representation of DMS
    
    >>> dms2dec(utf8(48°53'10.18"N))
    48.8866111111F
    
    >>> dms2dec(utf8(2°20'35.09"E))
    2.34330555556F
    
    >>> dms2dec(utf8(48°53'10.18"S))
    -48.8866111111F
    
    >>> dms2dec(utf8(2°20'35.09"W))
    -2.34330555556F
    
    """
    
    dms_str = re.sub(r'\s', '', dms_str)
    print(dms_str)    
    sign = -1 if re.search('[swSW]', dms_str) else 1
    
    numbers = filter(len, re.split('\D+', dms_str, maxsplit=4))

    degree = int(next(numbers))
    minute = int(next(numbers))
    second = int(next(numbers))
    #frac_seconds = int(next(numbers))
    print(f"degree:{degree} minutes:{minute} seconds:{second}")
    if minute < 2: minute = 0
    if second < 3: minute = 0
    #if frac_seconds < 3: minute = 0
     
    #degree = next(numbers)
    #minute = next(numbers) if len(numbers) >= 2 else '0'
    #second = next(numbers) if len(numbers) >= 3 else '0'
    #frac_seconds = next(numbers) if len(numbers) >= 4 else '0'
    
    #second += "." + frac_seconds
    return sign * (int(degree) + float(minute) / 60 + float(second) / 3600)


print(dms2dec(sys.argv[1]))
