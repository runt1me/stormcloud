from time import sleep

import logging

def execute_ping_loop(interval,name):
    while True:
        print("pinging server (thread %s)" % name)
        sleep(interval)