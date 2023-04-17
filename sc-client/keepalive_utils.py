from time import sleep
import json
import logging

import network_utils as scnet

def execute_ping_loop(interval,api_key,agent_id,name):
    while True:
        logging.log(logging.INFO,"Sending keepalive to server")
        keepalive_request_data = json.dumps({
            'request_type': 'keepalive',
            'api_key': api_key,
            'agent_id': agent_id
        })
        
        ret, response_data = scnet.tls_send_json_data(
            keepalive_request_data,
            200,
            show_json=True
        )

        sleep(interval)