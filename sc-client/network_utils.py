from datetime import datetime, timedelta
from os import walk
from time import sleep
import pathlib

import json
import requests

import socket, ssl
import logging

import crypto_utils

SERVER_NAME="127.0.0.1"
SERVER_PORT=5000

API_ENDPOINT_BACKUP_FILE         = 'https://%s:%d/api/backup-file'           % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_BACKUP_FILE_CHUNKED = 'http://%s:%d/api/backup-file-in-chunks' % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_KEEPALIVE           = 'https://%s:%d/api/keepalive'             % (SERVER_NAME,SERVER_PORT)

# Making this small for testing
# CHUNK_SIZE = 1024*1024
CHUNK_SIZE = 1024

def ship_file_to_server(api_key,agent_id,secret_key,path):
    encrypted_content, size_of_encrypted_content   = crypto_utils.encrypt_file(path,secret_key)
    encrypted_path, _ = crypto_utils.encrypt_content(path,secret_key)

    logging.log(logging.INFO,dump_file_info(path,size_of_encrypted_content))

    return upload_file_in_chunks(
        api_key,
        agent_id,
        encrypted_path.decode("utf-8"),
        encrypted_content.decode("utf-8"),
        size_of_encrypted_content
    )

def upload_file_in_chunks(api_key,agent_id,encrypted_path,encrypted_content,size_of_encrypted_content):
    total_chunks = size_of_encrypted_content // CHUNK_SIZE + 1
    expected_response_code = 200

    idx = 0
    for chunk_number in range(total_chunks):
        chunk = encrypted_content[idx:idx+CHUNK_SIZE]

        this_chunk_json_data = json.dumps({
            'request_type': "backup_file_in_chunks",
            'api_key': api_key,
            'agent_id': agent_id,
            'total_chunks': total_chunks,
            'chunk_number': chunk_number,
            'file_path': encrypted_path,
            'file_content_chunk': chunk
        })
        
        ret_code = post_one_chunk(this_chunk_json_data, expected_response_code)
        if ret_code != expected_response_code:
            logging.log(logging.ERROR, "Got bad return code from backup_file_in_chunks: %d" % ret_code)
            # TODO: figure out some kind of failure behavior here, try again X number of tries, go back to sleep, etc?
            # For now, just bailing if it cant send any one of the chunks
            break

        idx += CHUNK_SIZE

    return ret_code

def post_one_chunk(json_data_as_string, expected_response_code, show_json=False):
    headers = {'Content-type': 'application/json', 'Transfer-Encoding': 'chunked'}
    url = API_ENDPOINT_BACKUP_FILE_CHUNKED

    try:
        response = requests.post(url, headers=headers, data=json_data_as_string)

    except Exception as e:
        logging.log(logging.ERROR, "Send chunk failed: %s" % e)

    finally:
        if response:
            response_json = response.json()
            print("Client received response json: %s" % response_json)

            return response.status_code
        else:
            return 500

def tls_send_json_data(json_data_as_string, expected_response_code, show_json=False):
    response = None
    headers = {'Content-type': 'application/json', 'Transfer-Encoding': 'chunked'}
    json_data = json.loads(json_data_as_string)
    
    if 'backup_file' in json_data['request_type']:
        url = API_ENDPOINT_BACKUP_FILE
    elif 'keepalive' in json_data['request_type']:
        url = API_ENDPOINT_KEEPALIVE

    try:
        response = requests.post(url, headers=headers, data=json.dumps(json_data))

    except Exception as e:
        logging.log(logging.ERROR, "Send data failed: %s" % (e))

    finally:
        if response:
            response_json = response.json()
            logging.log(logging.INFO, "Received data: %s" % response_json)

            if response.status_code == expected_response_code:
                return (0, response_json)
        else:
            return (1, None)

def dump_file_info(path,size_of_encrypted_content):
    logging.log(logging.INFO,"==== SENDING FILE : INFO ====")
    logging.log(logging.INFO,"\tPATH: %s" %path)
    logging.log(logging.INFO,"\tSIZE WHEN ENCRYPTED: %d" %size_of_encrypted_content)