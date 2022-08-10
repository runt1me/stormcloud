import logging

import database_utils as db

def record_keepalive(device_id,current_time):
    logging.log(logging.INFO,"recording keepalive for device %d" %device_id)
    ret = db.update_callback_for_device(device_id,current_time,0)

    return ret

def initialize_logging():
    logging.basicConfig(
            filename='/var/log/stormcloud_ka.log',
            filemode='a',
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG
    )

