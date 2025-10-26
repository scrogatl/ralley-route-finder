import sys, csv
from persistqueue import Queue


q = Queue("path_to_queue")

print(f"qsize: {q.qsize()}")

input()

while q.qsize() > 0:
    item = q.get()
    print(f"Retrieved: {item}")
    q.task_done()


print(f"qsize: {q.qsize()}")
