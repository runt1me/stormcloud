import logging
import os
import sqlite3

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