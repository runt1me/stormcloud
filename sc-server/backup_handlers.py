import json
from datetime import datetime

import database_utils as db
import logging_utils, crypto_utils, backup_utils

import base64
import pathlib
from pathlib import Path

CHUNK_SIZE = 1024*1024

STRING_401_BAD_REQUEST = "Bad request."
RESPONSE_401_BAD_REQUEST = (
  401,json.dumps({'error':STRING_401_BAD_REQUEST})
)

def __logger__():
    return logging_utils.logger

def handle_register_new_device_request(request):
    __logger__().info("Server handling new device request.")

    customer_id = db.get_customer_id_by_api_key(request['api_key'])
    if not customer_id:
        return RESPONSE_401_BAD_REQUEST

    print(request)
    print(request['ip_address'])
    print(request['device_name'])

    device_name      = request['device_name']
    ip_address       = request['ip_address']
    device_type      = request['device_type']
    operating_system = request['operating_system']
    device_status    = request['device_status']

    last_callback = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stormcloud_path_to_secret_key = "/keys/%s/device/%s/secret.key" % (customer_id,db.get_next_device_id())

    key      = crypto_utils.create_key(stormcloud_path_to_secret_key)
    agent_id = crypto_utils.generate_agent_id()

    ret = db.add_or_update_device_for_customer(
        customer_id,
        device_name,
        device_type,
        ip_address,
        operating_system,
        device_status,
        last_callback,
        stormcloud_path_to_secret_key,
        agent_id
    )

    response_data = json.dumps({
        'register_new_device-response': 'thanks for the device',
        'secret_key': key.decode("utf-8"),
        'agent_id': agent_id
    })

    return 200, response_data

def handle_backup_file_request(request, file):
    __logger__().info("Server handling backup file request.")
    __logger__().info("File type: %s" % type(file))
    backup_utils.print_request_no_file(request)

    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return RESPONSE_401_BAD_REQUEST

    results = db.get_device_by_agent_id(request['agent_id'])
    if not results:
        return RESPONSE_401_BAD_REQUEST

    device_id,_,_,_,_,_,_,_,path_to_device_secret_key,_ = results

    #path_on_device, _ = crypto_utils.decrypt_msg(path_to_device_secret_key,request['file_path'].encode("UTF-8"),decode=True)
    path_on_device = base64.b64decode(request['file_path']).decode("utf-8")
    print("Path on device decoded: %s" % path_on_device)

    if not path_on_device:
        return RESPONSE_401_BAD_REQUEST

    path_on_server, device_root_directory_on_server = backup_utils.get_server_path(customer_id,device_id,path_on_device)

    file_size = backup_utils.stream_write_file_to_disk(path=path_on_server,file_handle=file,max_versions=3,chunk_size=CHUNK_SIZE)

    # TODO: eventually respond to client more quickly and queue the writes to disk / database calls until afterwards
    __logger__().info("Done writing file to %s" % path_on_server)

    # Not decrypting at this time due to issues with fernet and file size / memory constraints
    # result, file_size = crypto_utils.decrypt_in_place(path_to_device_secret_key,path_on_server,decode=False)

    # TODO: clean this up and put as a helper function in backup_utils
    if "\\" in path_on_device:
        p = pathlib.PureWindowsPath(r'%s'%path_on_device)
        path_on_device_posix = str(p.as_posix())
        directory_on_device = p.parents[0]
        directory_on_device_posix = str(directory_on_device.as_posix())
    else:
        # TODO: test does this work on unix?
        p = pathlib.Path(path_on_device)
        path_on_device_posix = path_on_device
        directory_on_device = p.parents[0]
        directory_on_device_posix = str(directory_on_device)

    file_name = backup_utils.get_file_name(path_on_server)
    file_path = backup_utils.get_file_path_without_name(path_on_server)
    file_type = backup_utils.get_file_type(path_on_server)

    _ = db.add_or_update_file_for_device(
        device_id,
        file_name,
        file_path,
        path_on_device,
        path_on_device_posix,
        directory_on_device_posix,
        file_size,
        file_type,
        path_on_server
    )

    return 200,json.dumps({'backup_file-response': 'Received file successfully.'})

