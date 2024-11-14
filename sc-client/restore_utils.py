import os
import json
import logging
import base64

import network_utils as scnet

def restore_file(file_path, api_key, agent_id, secret_key, version_id=None):
    path_for_request = base64.b64encode(str(file_path).encode("utf-8")).decode('utf-8')

    restore_file_request_data = json.dumps({
        'request_type': 'restore_file',
        'file_path': path_for_request,
        'api_key': api_key,
        'agent_id': agent_id,
        'version_id': version_id
    })

    status_code, response_data = scnet.tls_send_json_data_get(
        restore_file_request_data,
        200,
        show_json=False
    )
    
    logging.info("Status code returned: {}".format(status_code))
    logging.info("Response data returned: {}".format(response_data))

    if response_data:
        if 'file_content' in response_data:
            file_content = base64.b64decode(response_data['file_content'])
            write_result = write_file_to_disk(file_content, file_path)

            if write_result:
                logging.info(f"Successfully restored file {file_path}" + 
                           f" version {version_id}" if version_id else "")
                return True
            else:
                logging.warning(f"Failed to write restored file to disk: {file_path}")
                return False
        else:
            logging.warning("Got malformed response from restore_file request")
            return False
    else:
        logging.warning("Failed to get response from restore_file request")
        return False

def write_file_to_disk(file_content, file_path):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    with open(file_path, 'wb') as outfile:
        outfile.write(file_content)

    return True