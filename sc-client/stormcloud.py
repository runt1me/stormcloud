from time import sleep
from datetime import datetime, timedelta

import threading
import logging

import keepalive_utils

#number of seconds in between actions
ACTION_TIMER = 90

#updates based on number of threads created
THREAD_NUM = 0

def main():
    if not hash_db_exists():
        create_hash_db()

    else:
        hash_db = get_hash_db()

    action_loop_and_sleep()

def hash_db_exists():
    print("checking if hash db exists on machine")

def create_hash_db():
    print("creating new hash db")

def get_hash_db():
    print("getting hash database")

def action_loop_and_sleep():
    PREV_RUN_TIME = datetime.now() - timedelta(minutes=2)
    PREV_KEEPALIVE_FREQ = -1
    active_thread = None

    #daemon loop
    while True:
        settings = read_settings_file()
        CURRENT_RUN_TIME = datetime.now()
        CUR_KEEPALIVE_FREQ = int(settings['KEEPALIVE_FREQ'])
        BACKUP_TIME = int(settings['BACKUP_TIME'])

        #print("running at time %s with settings: %s" % (CURRENT_RUN_TIME,settings))

        if check_for_backup(BACKUP_TIME,CURRENT_RUN_TIME,PREV_RUN_TIME):
            perform_backup()

        if active_thread is None:
            active_thread = start_keepalive_thread(CUR_KEEPALIVE_FREQ)
        else:
            if active_thread.is_alive():
                if CUR_KEEPALIVE_FREQ != PREV_KEEPALIVE_FREQ:
                    kill_current_keepalive_thread(active_thread)
                    active_thread = start_keepalive_thread(CUR_KEEPALIVE_FREQ)
            else:
                active_thread = start_keepalive_thread(CUR_KEEPALIVE_FREQ)

        PREV_KEEPALIVE_FREQ = CUR_KEEPALIVE_FREQ
        PREV_RUN_TIME = CURRENT_RUN_TIME

        sleep(ACTION_TIMER)

def read_settings_file(fn="settings.cfg"):
    #TODO:
    #fail gracefully if settings are not complete?
    #revert to last known good settings?
    with open(fn,'r') as settings_file:
        settings_lines = [l for l in settings_file.read().split('\n') if l]
        settings_lines = [l for l in settings_lines if l[0] != "#"]

        settings = {}
        for s in settings_lines:
            settings[s.split()[0]] = s.split()[1]

    return settings

def check_for_backup(backup_time,current_run_time,previous_run_time):
    datetime_of_backup = datetime(
        year=datetime.now().year,
        month=datetime.now().month,
        day=datetime.now().day,
        hour=backup_time,
        minute=0,
        second=0
    )

    print("PREVIOUS RUN: %s" % previous_run_time)
    print("BACKUP TIME: %s" % datetime_of_backup)
    print("CURRENT RUN: %s" % current_run_time)

    if previous_run_time < datetime_of_backup and current_run_time > datetime_of_backup:
        return True
    else:
        return False

def perform_backup():
    print("\n\n\nBacking up!\n\n\n")
    exit()

def kill_current_keepalive_thread(active_thread):
    print(active_thread)

def start_keepalive_thread(freq):
    print("starting new keepalive thread with freq %d" % freq)

    #make thread with this function as a target
    t = threading.Thread(target=keepalive_utils.execute_ping_loop,args=(freq,"keepalive_thd"))
    t.start()

    print("returning from start thread")
    return t

if __name__ == "__main__":
    main()