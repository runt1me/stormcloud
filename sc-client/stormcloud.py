from time import sleep
from datetime import datetime, timedelta
import argparse
import platform
import os

import sqlite3

import threading
import logging

import keepalive_utils
import backup_utils
import logging_utils

#number of seconds in between actions
ACTION_TIMER = 90

#updates based on number of threads created
THREAD_NUM = 0

def main(settings_file_path,api_key_file_path,agent_id_file_path,hash_db_file_path):
    settings                = read_settings_file(settings_file_path)
    api_key                 = read_api_key_file(api_key_file_path)
    agent_id                = read_agent_id_file(agent_id_file_path)

    if int(settings['SEND_LOGS']):
        logging_utils.send_logs_to_server(api_key,agent_id)
    
    logging_utils.initialize_logging(uuid=agent_id)

    hash_db_conn = get_or_create_hash_db(hash_db_file_path)
    action_loop_and_sleep(settings=settings,api_key=api_key,agent_id=agent_id,dbconn=hash_db_conn)

def action_loop_and_sleep(settings, api_key, agent_id, dbconn):
    # For the first run, just check if the backup should have been run in the previous 10 minutes
    prev_run_time = datetime.now() - timedelta(minutes=10)
    prev_keepalive_freq = -1
    active_thread = None

    while True:
        cur_run_time = datetime.now()
        cur_keepalive_freq = int(settings['KEEPALIVE_FREQ'])
        backup_time        = int(settings['BACKUP_TIME'])
        backup_paths           = settings['BACKUP_PATHS']
        recursive_backup_paths = settings['RECURSIVE_BACKUP_PATHS']

        logging.log(logging.INFO,"Stormcloud is running with settings: %s" % (settings))

        #if backup_utils.check_for_backup(backup_time,cur_run_time,prev_run_time):
        backup_utils.perform_backup(backup_paths,recursive_backup_paths,api_key,agent_id,dbconn)

        if active_thread is None:
            active_thread = start_keepalive_thread(cur_keepalive_freq,api_key,agent_id)
        else:
            if active_thread.is_alive():
                if settings_have_changed(cur_keepalive_freq,prev_keepalive_freq):
                    kill_current_keepalive_thread(active_thread)
                    active_thread = start_keepalive_thread(cur_keepalive_freq,api_key,agent_id)
            else:
                active_thread = start_keepalive_thread(cur_keepalive_freq,api_key,agent_id)

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
        backup_paths_line           = settings_lines.index("BACKUP_PATHS")
        recursive_backup_paths_line = settings_lines.index("RECURSIVE_BACKUP_PATHS")

        for s in settings_lines[0:backup_paths_line]:
            settings[s.split()[0]] = s.split()[1]

        backup_paths = []
        recursive_backup_paths = []

        for s in settings_lines[backup_paths_line+1:recursive_backup_paths_line]:
            backup_paths.append(s)

        for s in settings_lines[recursive_backup_paths_line+1:]:
            recursive_backup_paths.append(s)

        settings["BACKUP_PATHS"]           = backup_paths
        settings["RECURSIVE_BACKUP_PATHS"] = recursive_backup_paths

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

def start_keepalive_thread(freq,api_key,agent_id):
    logging.log(logging.INFO,"starting new keepalive thread with freq %d" % freq)

    #make thread with this function as a target
    t = threading.Thread(target=keepalive_utils.execute_ping_loop,args=(freq,api_key,agent_id,"keepalive_thd"))
    t.start()

    logging.log(logging.INFO,"returning from start thread")
    return t

def get_or_create_hash_db(hash_db_file_path):
    if not hash_db_exists(hash_db_file_path):
        return create_hash_db(hash_db_file_path)

    else:
        return get_hash_db(hash_db_file_path)

def hash_db_exists(path_to_file):
    return os.path.exists(path_to_file)

def create_hash_db(path_to_file):
    logging.log(logging.INFO,"creating new hash db")

    conn = sqlite3.connect(path_to_file) 
    c = conn.cursor()

    c.execute('''
          CREATE TABLE IF NOT EXISTS files
          ([file_id] INTEGER PRIMARY KEY, [file_name] TEXT, [md5] TEXT)
          ''')

    conn.commit()
    return conn

def get_hash_db(path_to_file):
    return sqlite3.connect(path_to_file)

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
    parser.add_argument("-d", "--hash-db", type=str, default="schash.db", help="Path to hash db file (default=./schash.db")

    args = parser.parse_args()

    main(args.settings_file,args.api_key,args.agent_id,args.hash_db)