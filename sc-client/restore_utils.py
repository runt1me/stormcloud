import os
import json
import logging

import crypto_utils
import network_utils as scnet

def restore_file(file_path, api_key, agent_id, secret_key):
    encrypted_path, _ = crypto_utils.encrypt_content(file_path,secret_key)

    restore_file_request_data = json.dumps({
        'request_type': 'restore_file',
        'file_path': encrypted_path.decode("utf-8"),
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
            file_content = response_data['file_content'].encode("utf-8")

            write_result   = write_file_to_disk(file_content, file_path)

            if write_result:
                decrypt_result, file_size = crypto_utils.decrypt_in_place(file_path, secret_key)

                if decrypt_result:
                    return True

                else:
                    logging.log(logging.WARNING, "Failed to decrypt file in place.")
                    return False
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
    with open(file_path, 'wb') as outfile_encrypted:
        outfile_encrypted.write(file_content)

    return True