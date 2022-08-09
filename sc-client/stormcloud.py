from time import sleep
from datetime import datetime, timedelta
import argparse
import platform

import threading
import logging

import keepalive_utils
import backup_utils
import logging_utils

#number of seconds in between actions
ACTION_TIMER = 90

#updates based on number of threads created
THREAD_NUM = 0

# TODOs (general)
# Need to address the device identification problem
# i.e. if a device DHCPs to a new address, will it be able to backup files?
# may need to auto-create new devices if they come in via a valid API key without known hostname/ip.
# that potentially carries some security risk though, i.e. if the API key is compromised.
# Side note, may need to prevent new devices from being added through the API if only the API key is provided.
# Maybe I need an API secret per user instead of just per device.
# also probably just need to get better at the device identification problem in general. sigh.

def main(settings_file_path,api_key_file_path,agent_id_file_path):
    settings                = read_settings_file(settings_file_path)
    api_key                 = read_api_key_file(api_key_file_path)
    agent_id                = read_agent_id_file(agent_id_file_path)

    if int(settings['SEND_LOGS']):
        logging_utils.send_logs_to_server(api_key,agent_id)
    
    logging_utils.initialize_logging(uuid=agent_id)

    #TODO: check for updates???
    hash_db = get_or_create_hash_db()
    action_loop_and_sleep(settings=settings,api_key=api_key,agent_id=agent_id)

def action_loop_and_sleep(settings, api_key, agent_id):
    # For the first run, just check if the backup should have been run in the previous 10 minutes
    prev_run_time = datetime.now() - timedelta(minutes=10)
    prev_keepalive_freq = -1
    active_thread = None

    #daemon loop
    while True:
        cur_run_time = datetime.now()
        cur_keepalive_freq = int(settings['KEEPALIVE_FREQ'])
        backup_time        = int(settings['BACKUP_TIME'])
        backup_paths       =     settings['BACKUP_PATHS']

        logging.log(logging.INFO,"Stormcloud is running with settings: %s" % (settings))

        #if backup_utils.check_for_backup(backup_time,cur_run_time,prev_run_time):
        backup_utils.perform_backup(backup_paths,api_key,agent_id)

        if active_thread is None:
            active_thread = start_keepalive_thread(cur_keepalive_freq,api_key)
        else:
            if active_thread.is_alive():
                if settings_have_changed(cur_keepalive_freq,prev_keepalive_freq):
                    kill_current_keepalive_thread(active_thread)
                    active_thread = start_keepalive_thread(cur_keepalive_freq,api_key)
            else:
                active_thread = start_keepalive_thread(cur_keepalive_freq,api_key)

        prev_keepalive_freq = cur_keepalive_freq
        prev_run_time = cur_run_time

        sleep(ACTION_TIMER)

def read_settings_file(fn):
    #TODO: fail gracefully if settings are not complete?
    #revert to last known good settings?
    with open(fn,'r') as settings_file:
        settings_lines = [l for l in settings_file.read().split('\n') if l]
        settings_lines = [l for l in settings_lines if l[0] != "#"]

        settings = {}
        backup_paths_line = -1
        for idx,s in enumerate(settings_lines):
            if s == "BACKUP_PATHS":
                backup_paths_line = idx
                break

            settings[s.split()[0]] = s.split()[1]

        backup_paths = []
        for s in settings_lines[backup_paths_line+1:]:
            backup_paths.append(s)

        settings["BACKUP_PATHS"] = backup_paths

    return settings

def settings_have_changed(cur_keepalive_freq,prev_keepalive_freq):
    if cur_keepalive_freq != prev_keepalive_freq:
        return True
    else:
        return False

def kill_current_keepalive_thread(active_thread):
    #TODO: this function
    #maybe change to multiprocessing instead of multithreading???
    logging.log(logging.INFO,"killing %s" % active_thread)

def start_keepalive_thread(freq,api_key):
    logging.log(logging.INFO,"starting new keepalive thread with freq %d" % freq)

    #make thread with this function as a target
    t = threading.Thread(target=keepalive_utils.execute_ping_loop,args=(freq,api_key,"keepalive_thd"))
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

def read_api_key_file(keyfile_path):
    with open(keyfile_path,'rb') as keyfile:
        api_key = keyfile.read()

    return api_key.decode("utf-8")

def read_agent_id_file(agent_id_file_path):
    with open(agent_id_file_path, 'rb') as agentfile:
        agent_id = agentfile.read()

    return agent_id.decode("utf-8")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--settings-file",type=str,default="settings.cfg",help="Path to settings file (default=./settings.cfg)")
    parser.add_argument("-a", "--api-key", type=str, default="api.key", help="Path to API key file (default=./api.key)")
    parser.add_argument("-g", "--agent-id", type=str, default="agent_id", help="Path to the Agent ID file (default=./agent_id")

    args = parser.parse_args()

    main(args.settings_file,args.api_key,args.agent_id)