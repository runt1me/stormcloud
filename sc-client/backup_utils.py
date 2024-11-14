from datetime import datetime

import pathlib
import hashlib
import os

import logging
import network_utils

import traceback

BACKUP_STATUS_NO_CHANGE = 0
BACKUP_STATUS_CHANGE    = 1

def perform_backup(paths, paths_recursive, api_key, agent_id, secret_key, dbconn, ignore_hash, systray):
    """Enhanced backup function with better error handling"""
    logging.info("Beginning backup!")
    
    try:
        if not systray:
            logging.warning("Systray object is None - creating dummy systray")
            # Create dummy systray if none provided
            class DummySystray:
                def update(self, hover_text=""):
                    pass
            systray = DummySystray()

        systray.update(hover_text="Stormcloud Backup Engine - Backing up now")
        
        if ignore_hash:
            logging.info("Ignoring the hash database and attempting to force backup of files.")

        # Log paths being processed
        logging.info(f"Processing non-recursive paths: {paths}")
        logging.info(f"Processing recursive paths: {paths_recursive}")

        # Process each path with detailed error handling
        for path in paths:
            try:
                if not os.path.exists(path):
                    logging.error(f"Path does not exist: {path}")
                    continue
                    
                logging.info(f"Processing file: {path}")
                path_obj = pathlib.Path(path)
                
                if path_obj.is_file():
                    process_file(path_obj, api_key, agent_id, secret_key, dbconn, ignore_hash)
                elif path_obj.is_dir():
                    logging.info(f"Processing directory: {path}")
                    for file_obj in [p for p in path_obj.iterdir() if p.is_file()]:
                        process_file(file_obj, api_key, agent_id, secret_key, dbconn, ignore_hash)
                        
            except Exception as e:
                logging.error(f"Error processing path {path}: {str(e)}", exc_info=True)
                raise  # Re-raise to be caught by outer try/except

        process_paths_recursive(paths_recursive, api_key, agent_id, secret_key, dbconn, ignore_hash)
        
        systray.update(hover_text="Stormcloud Backup Engine")
        logging.info("Backup completed successfully")
        return True
        
    except Exception as e:
        logging.error(f"Backup failed: {str(e)}", exc_info=True)
        systray.update(hover_text="Stormcloud Backup Engine - Backup Failed")
        raise

def process_paths_nonrecursive(paths,api_key,agent_id,secret_key,dbconn,ignore_hash):
    for path in paths:
        try:
            logging.log(logging.INFO,"==   %s   ==" % path)
            path_obj = pathlib.Path(path)

            if path_obj.is_file():
                process_file(path_obj,api_key,agent_id,secret_key,dbconn,ignore_hash)

            elif path_obj.is_dir():
                for file_obj in [p for p in path_obj.iterdir() if p.is_file()]:
                    process_file(file_obj,api_key,agent_id,secret_key,dbconn,ignore_hash)

        except Exception as e:
            logging.log(logging.WARN, "%s" % traceback.format_exc())
            logging.log(logging.WARN, "Caught exception when trying to process path %s: %s" % (path,e))

def process_paths_recursive(paths,api_key,agent_id,secret_key,dbconn,ignore_hash):
    if not(paths):
        return
        
    for path in paths:
        try:
            logging.log(logging.INFO, "==   %s (-R)  ==" % path)
            path_obj = pathlib.Path(path)

            process_one_path_recursive(path_obj,api_key,agent_id,secret_key,dbconn,ignore_hash)
        except Exception as e:
            logging.log(logging.WARN, "Caught (higher-level) exception when trying to process recursive path %s: %s" % (path,e))

def process_one_path_recursive(target_path,api_key,agent_id,secret_key,dbconn,ignore_hash):
    for file in target_path.iterdir():
        if file.is_dir():
            try:
                process_one_path_recursive(file,api_key,agent_id,secret_key,dbconn,ignore_hash)
            except Exception as e:
                logging.log(logging.WARN, "Caught (lower-level) exception when trying to process recursive path %s: %s" % (target_path,e))
        else:
            process_file(file,api_key,agent_id,secret_key,dbconn,ignore_hash)

def process_file(file_path_obj, api_key, agent_id, secret_key, dbconn, ignore_hash):
    """Enhanced process_file with better error handling"""
    try:
        logging.info(f"Processing file: {file_path_obj}")
        
        if not ignore_hash:
            status = check_hash_db(file_path_obj, dbconn)
        else:
            status = BACKUP_STATUS_CHANGE

        if status == BACKUP_STATUS_NO_CHANGE:
            logging.info("No change to file, continuing")
            return True

        elif status == BACKUP_STATUS_CHANGE:
            logging.info(f"Backing up file: {file_path_obj.name}")

            ret = network_utils.ship_file_to_server(api_key, agent_id, secret_key, file_path_obj.resolve())
            if ret == 200:
                if dbconn:  # Only update hash if we have a db connection
                    update_hash_db(file_path_obj, dbconn)
                logging.info(f"Successfully backed up file: {file_path_obj.name}")
                return True
            else:
                logging.error(f"Server returned non-200 status code: {ret}")
                return False
                
    except Exception as e:
        logging.error(f"Error processing file {file_path_obj}: {str(e)}", exc_info=True)
        raise

def check_hash_db(file_path_obj,conn):
    cursor = conn.cursor()
    file_path = str(file_path_obj)

    results = is_file_in_db(file_path, cursor)
    
    if not results:
        logging.log(logging.INFO,"Could not find file in hash database.")
        return BACKUP_STATUS_CHANGE

    else:
        file_name, md5_from_db = results[0]
        logging.log(logging.INFO,"== %s == " % file_name)
        logging.log(logging.INFO,"Got md5 from database: %s" % md5_from_db)

        current_md5 = get_md5_hash(file_path)
        logging.log(logging.INFO,"Got md5 hash from file: %s" % current_md5)

        if md5_from_db == current_md5:
            return BACKUP_STATUS_NO_CHANGE
        else:
            return BACKUP_STATUS_CHANGE

def update_hash_db(file_path_obj,conn):
    cursor      = conn.cursor()
    file_path   = str(file_path_obj)
    results     = is_file_in_db(file_path, cursor)
    md5         = get_md5_hash(file_path)

    if not results:
        insert_into_hash_db(md5, file_path, conn, cursor)
    else:
        update_hash_in_db(md5, file_path, conn, cursor)

    logging.log(logging.INFO, "Updated file hash in database.")

def insert_into_hash_db(md5, file_path, conn, cursor):
    cursor.execute('''INSERT INTO files (file_name, md5) VALUES (?,?)''',(file_path,md5)) 
    conn.commit()

def update_hash_in_db(md5, file_path, conn, cursor):
    cursor.execute('''UPDATE files SET md5 = ? WHERE file_name = ?''',(md5,file_path))
    conn.commit()

def is_file_in_db(file_path, cursor):
    cursor.execute('''SELECT file_name,md5 FROM files WHERE file_name = ?;''', (file_path,))
    return cursor.fetchall()

def get_md5_hash(path_to_file):
    with open(path_to_file, "rb") as f:
        file_hash = hashlib.md5()
        while chunk := f.read(8192):
            file_hash.update(chunk)

    return file_hash.hexdigest()
    
def print_rename(old, new):
    """Enhanced rename logging"""
    logging.info("== RENAMING ==")
    logging.info(f"From: {old}")
    logging.info(f"To:   {new}")
    
    # Verify paths look valid
    if ':' in new or ':' in old:
        logging.warning("WARNING: Found ':' in path which may indicate unconverted Windows path")