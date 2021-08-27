from time import sleep
import socket
import sys

import logging

import crypto_utils

CONNECTION_SERVER = "www2.darkage.io"
CONNECTION_PORT = 8081

def send_logfile_to_server():
    logfile_raw = get_most_recent_logfile()

    sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    server_address = (CONNECTION_SERVER,CONNECTION_PORT)

    logging.log(logging.INFO,"sending logfile to %s port %s" % server_address)
    sock.connect(server_address)

    try:
        logfile = wrap_logfile(client_id,logfile_raw)
        sock.sendall(logfile)

        #bytes expected to be sent and recvd
        amount_recvd = 0
        amount_expected = 16

        while amount_recvd < amount_expected:
            data = sock.recv(16)
            amount_recvd += len(data)
            logging.log(logging.INFO,"received %s" % data)

    finally:
        logging.log(logging.INFO,"closing socket")
        sock.close()

def wrap_logfile(client_id,logfile_raw):
    #TODO: encrypt!!
    msg_text = '%d,%d' % (client_id,random.randint(0,1000000))
    
    #pad message
    len_to_pad = PACKET_LEN - len(msg_text)
    logging.log(logging.INFO,"adding %d characters to msg %s" % (len_to_pad,msg_text))

    #encode ascii to convert str to bytes
    final_msg = (msg_text + ("." * len_to_pad)).encode('ascii')
    return final_msg

def get_most_recent_logfile():
    #TODO: look for all files that have name patterned client_CID*.log
    #send most recent logfile

def initialize_logging(client_id):
    logging.basicConfig(
        filename='client_%s_%s.log' % (client_id,datetime.now().strftime("%Y-%m-%d")),
        filemode='a',
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.DEBUG
    )
