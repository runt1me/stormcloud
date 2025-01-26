import json
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder

import os
import logging
import base64

SERVER_NAME="www2.darkage.io"
SERVER_PORT=8443

API_ENDPOINT_BACKUP_FILE             = 'https://%s:%d/api/backup-file'             % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_BACKUP_FILE_STREAM      = 'https://%s:%d/api/backup-file-stream'      % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_KEEPALIVE               = 'https://%s:%d/api/keepalive'               % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_RESTORE_FILE            = 'https://%s:%d/api/restore-file'            % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_REGISTER_BACKUP_FOLDERS = 'https://%s:%d/api/register-backup-folders' % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_FILE_METADATA           = 'https://%s:%d/api/file-metadata'           % (SERVER_NAME,SERVER_PORT)
# API_ENDPOINT_AUTHENTICATE            = 'https://%s:%d/api/validate-api-key'        % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_LOGIN                   = 'https://%s:%d/api/login'                   % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_SUMMARIZE_FILE          = 'https://%s:%d/api/summarize-file'          % (SERVER_NAME,SERVER_PORT)
API_ENDPOINT_SUBMIT_ERROR_LOG        = 'https://%s:%d/api/submit-error-log'        % (SERVER_NAME,SERVER_PORT)

def fetch_file_metadata(api_key, agent_id):
    url = API_ENDPOINT_FILE_METADATA
    headers = {'Content-Type': 'application/json'}
    data = {
        'api_key': api_key,
        'agent_id': agent_id
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logging.info("Received %d records from fetch_file_metadata" % len(response.json()['data']))
        return response.json()['data']
    except requests.RequestException as e:
        logging.error(f"Error fetching file metadata: {e}")
        return None

ONE_MB = 1024*1024
THRESHOLD_MB = 200
CHUNK_SIZE = ONE_MB

def authenticate_user(email: str, password: str, settings_path: str) -> dict:
    """Authenticate user with server using API key from settings"""
    import traceback
    
    url = API_ENDPOINT_LOGIN
    headers = {'Content-Type': 'application/json'}
    
    logging.info(f"Starting authentication attempt for user: {email}")
    
    try:
        data = {
            'email': email,
            'password': password
        }
        
        logging.info(f"Making authentication request to: {url}")
        
        response = requests.post(url, headers=headers, json=data)
        logging.info(f"Response status code: {response.status_code}")
        
        if response.status_code == 200:
            response_data = response.json()
            logging.info("Authentication response received and parsed")
            return response_data
        else:
            logging.error(f"Authentication failed with status code: {response.status_code}")
            logging.error(f"Response content: {response.text}")
            try:
                error_response = response.json()
                return {
                    'success': False,
                    'message': error_response.get('message', f"Server returned status code: {response.status_code}")
                }
            except:
                return {
                    'success': False,
                    'message': f"Server returned status code: {response.status_code}"
                }
            
    except Exception as e:
        logging.error(f"Authentication request failed with exception: {str(e)}")
        logging.error(f"Exception details: {traceback.format_exc()}")
        raise

def ship_file_to_server(api_key,agent_id,path):
    size = os.path.getsize(path)

    logging.log(logging.INFO,dump_file_info(path,size))

    if size > THRESHOLD_MB * ONE_MB:
        logging.log(logging.INFO, "File size over %dMB, using MultipartEncoder" % THRESHOLD_MB)

        ret = stream_upload_file(
            api_key,
            agent_id,
            path
        )

    else:
        ret = upload_file(
            api_key,
            agent_id,
            path
        )

    #crypto_utils.remove_temp_file(unencrypted_path_to_encrypted_file)
    return ret

def stream_upload_file(api_key,agent_id,local_file_path):
    url = API_ENDPOINT_BACKUP_FILE_STREAM
    response = None

    fields_dict = {
        'request_type': "backup_file",
        'api_key': api_key,
        'agent_id': agent_id,

        # WindowsPath obj -> str -> encode UTF-8 to convert to bytes -> base64 encode -> utf-8 decode -> serialize as JSON
        'file_path': base64.b64encode(str(local_file_path).encode("utf-8")).decode('utf-8'),

        # must provide 'filename' parameter in order for flask to properly interpret this as a file
        'file_content': ('filename', open(local_file_path, 'rb'), 'application/octet-stream')
    }

    enc = MultipartEncoder(fields=fields_dict)
    
    try:
        response = requests.post(url, data=enc, headers={'Content-Type': enc.content_type})
    except Exception as e:
        logging.log(logging.ERROR, "Got exception when trying to post MultipartEncoded file: %s" % e)
    finally:
        return response.status_code if response else 500

def upload_file(api_key,agent_id,local_file_path):
    url = API_ENDPOINT_BACKUP_FILE
    response = None

    json_data = json.dumps({
        'request_type': "backup_file",
        'api_key': api_key,
        'agent_id': agent_id,

        # WindowsPath obj -> str -> encode UTF-8 to convert to bytes -> base64 encode -> utf-8 decode -> serialize as JSON
        'file_path': base64.b64encode(str(local_file_path).encode("utf-8")).decode('utf-8')
    })

    # Since we're not streaming here, read the whole file into memory before sending.
    content = open(local_file_path, 'rb').read()

    # Including JSON object as part of "files" field
    # Because I cannot include both separately in a single multipart/form-data request.
    # See https://stackoverflow.com/questions/35939761/how-to-send-json-as-part-of-multipart-post-request
    files = {
        'file_content': content,
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
        logging.info("Sending headers for restore: {}".format(headers))
        logging.info("Sending json data for restore: {}".format(json.dumps(json_data)))
    
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

def dump_file_info(path,size):
    logging.log(logging.INFO,"== SENDING FILE : ==")
    logging.log(logging.INFO,"\tPATH: %s" %path)
    logging.log(logging.INFO,"\tSIZE: %d" %size)
    
def sync_backup_folders(settings):
    api_key = settings['API_KEY']
    agent_id = settings['AGENT_ID']
    backup_paths = settings['BACKUP_PATHS']
    recursive_backup_paths = settings['RECURSIVE_BACKUP_PATHS']

    # Prepare the folders data
    folders = []
    for path in backup_paths:
        folders.append({'path': path, 'is_recursive': 0})
    for path in recursive_backup_paths:
        folders.append({'path': path, 'is_recursive': 1})

    # Send the data to the server
    data = {
        'api_key': api_key,
        'agent_id': agent_id,
        'folders': folders
    }
    
    try:
        response = requests.post(API_ENDPOINT_REGISTER_BACKUP_FOLDERS, json=data)
        if response.status_code == 200 and response.json()['SUCCESS']:
            logging.info("Backup folders synchronized successfully")
        else:
            logging.error(f"Failed to synchronize backup folders: {response.json().get('message', 'Unknown error')}")
        return response.status_code == 200 and response.json()['SUCCESS']
    except Exception as e:
        logging.error(f"Error synchronizing backup folders: {str(e)}")
        return False
        
def summarize_file_with_ai(api_key: str, agent_id: str, filepath: str, content: str) -> dict:
    """Request AI summary of file from server."""
    url = API_ENDPOINT_SUMMARIZE_FILE
    headers = {'Content-Type': 'application/json'}
    data = {
        'api_key': api_key,
        'agent_id': agent_id,
        'filepath': base64.b64encode(str(filepath).encode("utf-8")).decode('utf-8'),
        'content': base64.b64encode(content.encode("utf-8")).decode('utf-8')
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Error getting file summary: {e}")
        return {
            'success': False, 
            'message': f"Failed to get summary: {str(e)}"
        }
        
def submit_error_log(api_key: str, agent_id: str, application_version: str, log_content: str, source: str):
    """Submit error log to server for analysis."""
    url = API_ENDPOINT_SUBMIT_ERROR_LOG
    headers = {'Content-Type': 'application/json'}

    data = {
        'api_key': api_key,
        'agent_id': agent_id,
        'application_version': application_version,
        'log_content': log_content,
        'source': source
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        print(response)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Error submitting error log: {e}")
        return {
            'success': False,
            'message': f"Failed to submit log: {str(e)}"
        }