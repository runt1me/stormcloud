import os
import json
import logging
import base64

import crypto_utils
import network_utils as scnet

def restore_file(file_path, api_key, agent_id, secret_key):
    path_for_request = base64.b64encode(str(file_path).encode("utf-8")).decode('utf-8')

    restore_file_request_data = json.dumps({
        'request_type': 'restore_file',
        'file_path': path_for_request,
        'api_key': api_key,
        'agent_id': agent_id
    })

    status_code, response_data = scnet.tls_send_json_data_get(
        restore_file_request_data,
        200,
        show_json=False
    )

    if response_data:
        if 'file_content' in response_data:
            file_content = base64.b64decode(response_data['file_content'])
            write_result   = write_file_to_disk(file_content, file_path)

            if write_result:
                return True

            else:
                logging.log(logging.WARNING, "Failed to write response file to disk.")
                return False
        else:
            logging.log(logging.WARNING, "Got response from restore_file which appeared to be malformed.")
            return False
    else:
        logging.log(logging.WARNING, "Failed to get response from restore_file.")
        return False

def write_file_to_disk(file_content, file_path):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    with open(file_path, 'wb') as outfile:
        outfile.write(file_content)

    return True