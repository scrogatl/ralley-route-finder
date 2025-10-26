import sys, csv
from persistqueue import Queue


q = Queue("path_to_queue")
with open(sys.argv[1]) as f:
    lines = [line.strip() for line in f if line.strip()]

count = 0
for line in lines:
    print(f"adding: {line}")
    q.put(line)
    count = count + 1

print(f"Enqueued {count} items")


