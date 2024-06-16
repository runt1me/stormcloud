import json
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder

import logging

import crypto_utils

SERVER_NAME="www2.darkage.io"
SERVER_PORT=8443

API_ENDPOINT_BACKUP_FILE         = 'https://%s:%d/api/backup-file'           % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_BACKUP_FILE_STREAM  = 'https://%s:%d/api/backup-file-stream'    % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_KEEPALIVE           = 'https://%s:%d/api/keepalive'             % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_RESTORE_FILE        = 'https://%s:%d/api/restore-file'          % (SERVER_NAME,SERVER_PORT)

ONE_MB = 1024*1024
THRESHOLD_MB = 200
CHUNK_SIZE = ONE_MB

def ship_file_to_server(api_key,agent_id,secret_key,path):
    unencrypted_path_to_encrypted_file, size_of_encrypted_content    = crypto_utils.encrypt_file(path,secret_key)
    encrypted_path, _ = crypto_utils.encrypt_content(path,secret_key)

    logging.log(logging.INFO,dump_file_info(path,size_of_encrypted_content))

    if size_of_encrypted_content > THRESHOLD_MB * ONE_MB:
        logging.log(logging.INFO, "File size over %dMB, using MultipartEncoder" % THRESHOLD_MB)

        ret = stream_upload_file(
            api_key,
            agent_id,
            encrypted_path,
            unencrypted_path_to_encrypted_file,
            size_of_encrypted_content
        )

    else:
        ret = upload_file(
            api_key,
            agent_id,
            encrypted_path,
            unencrypted_path_to_encrypted_file,
            size_of_encrypted_content
        )

    crypto_utils.remove_temp_file(unencrypted_path_to_encrypted_file)
    return ret

def stream_upload_file(api_key,agent_id,encrypted_path,unencrypted_path_to_encrypted_file,size_of_encrypted_content):
    url = API_ENDPOINT_BACKUP_FILE_STREAM
    response = None

    fields_dict = {
        'request_type': "backup_file",
        'api_key': api_key,
        'agent_id': agent_id,
        'file_path': encrypted_path.decode("UTF-8"),

        # must provide 'filename' parameter in order for flask to properly interpret this as a file
        'file_content': ('filename', open(unencrypted_path_to_encrypted_file, 'rb'), 'application/octet-stream')
    }

    enc = MultipartEncoder(fields=fields_dict)
    
    try:
        response = requests.post(url, data=enc, headers={'Content-Type': enc.content_type})
    except Exception as e:
        logging.log(logging.ERROR, "Got exception when trying to post MultipartEncoded file: %s" % e)
    finally:
        return response.status_code if response else 500

def upload_file(api_key,agent_id,encrypted_path,unencrypted_path_to_encrypted_file,size_of_encrypted_content):
    url = API_ENDPOINT_BACKUP_FILE
    response = None

    json_data = json.dumps({
        'request_type': "backup_file",
        'api_key': api_key,
        'agent_id': agent_id,
        'file_path': encrypted_path.decode("UTF-8")
    })

    # Since we're not streaming here, read the whole file into memory before sending.
    encrypted_content = open(unencrypted_path_to_encrypted_file, 'rb').read()

    # Including JSON object as part of "files" field
    # Because I cannot include both separately in a single multipart/form-data request.
    # See https://stackoverflow.com/questions/35939761/how-to-send-json-as-part-of-multipart-post-request
    files = {
        'file_content': encrypted_content,
        'json': (None, json_data, 'application/json')
    }

    try:
        response = requests.post(url, files=files)
    except Exception as e:
        logging.log(logging.ERROR, "Got exception when trying to post file: %s" % e)
    finally:
        return response.status_code if response else 500

def tls_send_json_data(json_data_as_string, expected_response_code, show_json=False):
    response = None
    headers = {'Content-type': 'application/json'}
    json_data = json.loads(json_data_as_string)
    
    if 'keepalive' in json_data['request_type']:
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

def tls_send_json_data_get(json_data_as_string, expected_response_code, show_json=False):
    response = None
    headers = {'Content-type': 'application/json'}
    json_data = json.loads(json_data_as_string)
    
    if 'restore_file' in json_data['request_type']:
        url = API_ENDPOINT_RESTORE_FILE

    try:
        response = requests.get(url, headers=headers, data=json.dumps(json_data))

    except Exception as e:
        logging.log(logging.ERROR, "Send data failed: %s" % (e))

    finally:
        if response:
            response_json = response.json()

            if show_json:
                logging.log(logging.INFO, "Received data: %s" % response_json)

            if response.status_code == expected_response_code:
                return (0, response_json)
        else:
            return (1, None)

def dump_file_info(path,size_of_encrypted_content):
    logging.log(logging.INFO,"==== SENDING FILE : INFO ====")
    logging.log(logging.INFO,"\tPATH: %s" %path)
    logging.log(logging.INFO,"\tSIZE WHEN ENCRYPTED: %d" %size_of_encrypted_content)