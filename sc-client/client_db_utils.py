import logging
import os
import sqlite3

def get_or_create_hash_db(hash_db_file_path):
    if not _hash_db_exists(hash_db_file_path):
        return _create_hash_db(hash_db_file_path)

    else:
        return _get_hash_db(hash_db_file_path)

def _hash_db_exists(path_to_file):
    return os.path.exists(path_to_file)

def _create_hash_db(path_to_file):
    logging.log(logging.INFO,"creating new hash db")

    conn = sqlite3.connect(path_to_file) 
    c = conn.cursor()

    c.execute('''
          CREATE TABLE IF NOT EXISTS files
          ([file_id] INTEGER PRIMARY KEY, [file_name] TEXT, [md5] TEXT)
          ''')

    conn.commit()
    return conn

def _get_hash_db(path_to_file):
    return sqlite3.connect(path_to_file)