from time import sleep
from datetime import datetime, timedelta

import threading
import logging

import keepalive_utils
import backup_utils
import logging_utils

#number of seconds in between actions
ACTION_TIMER = 90

#updates based on number of threads created
THREAD_NUM = 0

def main():
    settings = read_settings_file()
    logging_utils.initialize_logging(int(settings['CLIENT_ID']))

    if int(settings['SEND_LOGS']):
        logging_utils.send_logfile_to_server(int(settings['CLIENT_ID']))

    #TODO: check for updates???
    hash_db = get_or_create_hash_db()
    action_loop_and_sleep(settings=settings)

def action_loop_and_sleep(settings):
    PREV_RUN_TIME = datetime.now() - timedelta(minutes=2)
    PREV_KEEPALIVE_FREQ = -1
    active_thread = None

    #daemon loop
    while True:
        CURRENT_RUN_TIME = datetime.now()
        CUR_KEEPALIVE_FREQ = int(settings['KEEPALIVE_FREQ'])
        CUR_CLIENT_ID = int(settings['CLIENT_ID'])
        BACKUP_TIME = int(settings['BACKUP_TIME'])
        BACKUP_PATHS = settings['BACKUP_PATHS']

        logging.log(logging.INFO,"running at time %s with settings: %s" % (CURRENT_RUN_TIME,settings))

        #if backup_utils.check_for_backup(BACKUP_TIME,CURRENT_RUN_TIME,PREV_RUN_TIME):
        backup_utils.perform_backup(BACKUP_PATHS,CUR_CLIENT_ID)

        if active_thread is None:
            active_thread = start_keepalive_thread(CUR_KEEPALIVE_FREQ,CUR_CLIENT_ID)
        else:
            if active_thread.is_alive():
                if settings_have_changed(CUR_KEEPALIVE_FREQ,PREV_KEEPALIVE_FREQ,CUR_CLIENT_ID,PREV_CLIENT_ID):
                    kill_current_keepalive_thread(active_thread)
                    active_thread = start_keepalive_thread(CUR_KEEPALIVE_FREQ,CUR_CLIENT_ID)
            else:
                active_thread = start_keepalive_thread(CUR_KEEPALIVE_FREQ,CUR_CLIENT_ID)

        PREV_KEEPALIVE_FREQ = CUR_KEEPALIVE_FREQ
        PREV_CLIENT_ID = CUR_CLIENT_ID
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

def settings_have_changed(CUR_KEEPALIVE_FREQ,PREV_KEEPALIVE_FREQ,CUR_CLIENT_ID,PREV_CLIENT_ID):
    if CUR_KEEPALIVE_FREQ != PREV_KEEPALIVE_FREQ:
        return True
    elif CUR_CLIENT_ID != PREV_CLIENT_ID:
        return True
    else:
        return False

def kill_current_keepalive_thread(active_thread):
    #TODO: this function
    #maybe change to multiprocessing instead of multithreading???
    logging.log(logging.INFO,"killing %s" % active_thread)

def start_keepalive_thread(freq,client_id):
    logging.log(logging.INFO,"starting new keepalive thread with freq %d" % freq)

    #make thread with this function as a target
    t = threading.Thread(target=keepalive_utils.execute_ping_loop,args=(freq,client_id,"keepalive_thd"))
    t.start()

    logging.log(logging.INFO,"returning from start thread")
    return t

def get_or_create_hash_db():
    if not hash_db_exists():
        return create_hash_db()

    else:
        return get_hash_db()

def hash_db_exists():
    #TODO: this function
    logging.log(logging.INFO,"checking if hash db exists on machine")

def create_hash_db():
    #TODO: this function
    logging.log(logging.INFO,"creating new hash db")

def get_hash_db():
    #TODO: this function
    logging.log(logging.INFO,"getting hash database")

if __name__ == "__main__":
    main()