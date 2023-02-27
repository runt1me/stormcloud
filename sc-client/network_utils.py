from datetime import datetime, timedelta
from os import walk
from time import sleep
import pathlib

import json
import requests

import socket, ssl
import logging

import crypto_utils

SERVER_NAME="www2.darkage.io"
SERVER_PORT=8443

API_ENDPOINT_BACKUP_FILE         = 'https://%s:%d/api/backup-file'         % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_KEEPALIVE           = 'https://%s:%d/api/keepalive'           % (SERVER_NAME,SERVER_PORT)

def ship_file_to_server(api_key,agent_id,secret_key,path):
    encrypted_content, encrypted_size   = crypto_utils.encrypt_file(path,secret_key)
    encrypted_path, encrypted_path_size = crypto_utils.encrypt_content(path,secret_key)

    file_backup_request_data = json.dumps({
        'request_type': "backup_file",
        'api_key': api_key,
        'agent_id': agent_id,
        'file_content': encrypted_content.decode("utf-8"),
        'file_path': encrypted_path.decode("utf-8")
    })

    logging.log(logging.INFO,dump_file_info(path,encrypted_size))
    ret, response_data = tls_send_json_data(file_backup_request_data, "backup_file-response")

    return ret

def tls_send_json_data(json_data_as_string, expected_response_data, show_json=False):
    headers = {'Content-type': 'application/json'}
    if not validate_json(json_data_as_string):
        logging.log(logging.INFO, "Invalid JSON data received in tls_send_json_data(); not sending to server.")
        return (1, None)

    json_data = json.loads(json_data_as_string)
    
    if 'backup_file' in json_data['request_type']:
        url = API_ENDPOINT_BACKUP_FILE
    elif 'keepalive' in json_data['request_type']:
        url = API_ENDPOINT_KEEPALIVE

    try:
        if show_json:
            logging.log(logging.INFO, "Sending %s" %json_data)
        
        response = requests.post(url, headers=headers, data=json.dumps(json_data))

    except Exception as e:
        logging.log(logging.ERROR, "Send data failed: %s" % (e))

    finally:
        if response:
            response_json = response.json()
            logging.log(logging.INFO, "Received data: %s" % response_json)

            if expected_response_data in response_json:
                return (0, response_json)
        else:
            return (1, None)

def validate_json(data):
    try:
        json.loads(data)
    except json.decoder.JSONDecodeError:
        return False
    else:
        return True

def dump_file_info(path,encrypted_size):
    logging.log(logging.INFO,"==== SENDING FILE : INFO ====")
    logging.log(logging.INFO,"\tPATH: %s" %path)
    logging.log(logging.INFO,"\tSIZE WHEN ENCRYPTED: %d" %encrypted_size)

def calculate_timeout(data_length):
    # TODO: send data in chunks
    return 300