from time import sleep

import logging

def execute_ping_loop(interval,name):
    while True:
        sleep(interval)
        print("pinging server (thread %d)" % name)