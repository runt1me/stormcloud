from time import sleep
import random

import socket
import sys
import json

import logging

import network_utils as scnet

SERVER_NAME = "www2.darkage.io"
SERVER_PORT = 7443

def execute_ping_loop(interval,api_key,agent_id,name):
    while True:
        logging.log(logging.INFO,"Sending keepalive to %s:%s" % (SERVER_NAME,SERVER_PORT))
        keepalive_request_data = json.dumps({
            'request_type': 'keepalive',
            'api_key': api_key,
            'agent_id': agent_id
        })
        
        ret, response_data = scnet.tls_send_json_data(
            keepalive_request_data,
            'keepalive-response',
            SERVER_NAME,
            SERVER_PORT,
            show_json=True
        )

        sleep(interval)