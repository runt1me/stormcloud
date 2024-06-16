from time import sleep
from datetime import datetime
import argparse
import os

import sqlite3
import yaml

import threading
import logging

import sslkeylog

import keepalive_utils
import backup_utils
import logging_utils
import reconfigure_utils

from infi.systray import SysTrayIcon   # pip install infi.systray

ACTION_TIMER = 90

def main(settings_file_path,hash_db_file_path,ignore_hash_db):
    # Honor SSLKEYLOGFILE if set by the OS
    sslkeylog.set_keylog(os.environ.get('SSLKEYLOGFILE'))

    settings                = read_yaml_settings_file(settings_file_path)

    if int(settings['SEND_LOGS']):
        logging_utils.send_logs_to_server(settings['API_KEY'],settings['AGENT_ID'],settings['SECRET_KEY'])
    
    logging_utils.initialize_logging(uuid=settings['AGENT_ID'])

    hash_db_conn = get_or_create_hash_db(hash_db_file_path)

    systray_menu_options = (
        (
            "Backup now",
            None,
            lambda x: logging.log(logging.INFO, "User clicked 'Backup now', but backup is always running.")
        )
    ,)
    systray = SysTrayIcon("stormcloud.ico", "Stormcloud Backup Engine", systray_menu_options)
    systray.start()

    action_loop_and_sleep(settings=settings,settings_file_path=settings_file_path,dbconn=hash_db_conn,ignore_hash=ignore_hash_db,systray=systray)

def action_loop_and_sleep(settings, settings_file_path, dbconn, ignore_hash, systray):
    active_thread = None
    update_thread = None

    while True:
        cur_keepalive_freq = int(settings['KEEPALIVE_FREQ'])
        backup_paths           = settings['BACKUP_PATHS']
        recursive_backup_paths = settings['RECURSIVE_BACKUP_PATHS']
        api_key                = settings['API_KEY']
        agent_id               = settings['AGENT_ID']
        secret_key             = settings['SECRET_KEY']

        logging.log(logging.INFO,"Stormcloud is running with settings: %s"
            % ([(s, settings[s]) for s in settings.keys() if s != 'SECRET_KEY'])
        )

        if update_thread is None or not update_thread.is_alive():
            update_thread = threading.Thread(target=reconfigure_utils.fetch_and_update_backup_paths, args=(settings_file_path, settings['API_KEY'], settings['AGENT_ID']))
            update_thread.start()

        if active_thread is None:
            active_thread = start_keepalive_thread(cur_keepalive_freq,api_key,agent_id,secret_key)
        else:
            if active_thread.is_alive():
                pass
            else:
                active_thread = start_keepalive_thread(cur_keepalive_freq,api_key,agent_id,secret_key)

        backup_utils.perform_backup(backup_paths,recursive_backup_paths,api_key,agent_id,secret_key,dbconn,ignore_hash,systray)

        sleep(ACTION_TIMER)

def read_yaml_settings_file(fn):
    with open(fn, 'r') as settings_file:
        return yaml.safe_load(settings_file)

def start_keepalive_thread(freq,api_key,agent_id,secret_key):
    logging.log(logging.INFO,"starting new keepalive thread with freq %d" % freq)

    t = threading.Thread(target=keepalive_utils.execute_ping_loop,args=(freq,api_key,agent_id,secret_key))
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

if __name__ == "__main__":
    description = r"""

        ______     ______   ______     ______     __    __                    
       /\  ___\   /\__  _\ /\  __ \   /\  == \   /\ "-./  \                   
       \ \___  \  \/_/\ \/ \ \ \/\ \  \ \  __<   \ \ \-./\ \                  
        \/\_____\    \ \_\  \ \_____\  \ \_\ \_\  \ \_\ \ \_\                 
         \/_____/     \/_/   \/_____/   \/_/ /_/   \/_/  \/_/                 
                                                                              
                    ______     __         ______     __  __     _____         
                   /\  ___\   /\ \       /\  __ \   /\ \/\ \   /\  __-.       
                   \ \ \____  \ \ \____  \ \ \/\ \  \ \ \_\ \  \ \ \/\ \      
                    \ \_____\  \ \_____\  \ \_____\  \ \_____\  \ \____-      
                     \/_____/   \/_____/   \/_____/   \/_____/   \/____/      
                                                                              
                                   ______     ______     ______     ______    
                                  /\  ___\   /\  __ \   /\  == \   /\  ___\   
                                  \ \ \____  \ \ \/\ \  \ \  __<   \ \  __\   
                                   \ \_____\  \ \_____\  \ \_\ \_\  \ \_____\ 
                                    \/_____/   \/_____/   \/_/ /_/   \/_____/ 
                                                                                                                                                                                                                                                                           

    """

    description += 'Welcome to Stormcloud, the best backup system!'
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-s", "--settings-file",type=str,default="settings.cfg",help="Path to settings file (default=./settings.cfg)")
    parser.add_argument("-d", "--hash-db", type=str, default="schash.db", help="Path to hash db file (default=./schash.db")
    parser.add_argument("-o", "--ignore-hash-db", action="store_true", help="override the hash db, to backup files even if they haven't changed")

    args = parser.parse_args()
    main(args.settings_file,args.hash_db,args.ignore_hash_db)