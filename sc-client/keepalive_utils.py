from time import sleep
import json
import logging

import network_utils as scnet
import restore_utils

from win10toast import ToastNotifier

def execute_ping_loop(interval,api_key,agent_id):
    while True:
        logging.log(logging.INFO,"Sending keepalive to server")
        keepalive_request_data = json.dumps({
            'request_type': 'keepalive',
            'api_key': api_key,
            'agent_id': agent_id
        })
        
        status_code, response_data = scnet.tls_send_json_data(
            keepalive_request_data,
            200,
            show_json=True
        )

        if response_data:
            if 'restore_queue' in response_data:
                restore_queue = response_data['restore_queue']
                if restore_queue:
                    for file_name in restore_queue:
                        if restore_utils.restore_file(file_name, api_key, agent_id):
                            logging.log(logging.INFO, "Successfully restored file! Wrote to: %s" % file_name)
                        else:
                            logging.log(logging.WARNING, "Failed to restore file: Attempted: %s" % file_name)
                    
                    try:
                        toaster = ToastNotifier()
                        toaster.show_toast("Stormcloud restore complete",
                            "Finished restoring %d files!" % len(restore_queue),
                            duration=10,
                            icon_path=""
                        )
                    except:
                        logging.log(logging.INFO, "Failed to display toast notification to user upon successful restore.")

            else:
                logging.log(logging.WARNING, "Got keepalive response from server that appeared to be malformed.")

        sleep(interval)