import pathlib
import logging
import os

import crypto_utils

def store_file(customer_id,device_id,path_to_device_secret_key,file_path,file_raw_content):
    decrypted_raw_content, _ = crypto_utils.decrypt_msg(path_to_device_secret_key,file_raw_content,decode=False)
    decrypted_path, _        = crypto_utils.decrypt_msg(path_to_device_secret_key,file_path,decode=True)

    path_on_server, device_root_directory_on_server = get_server_path(customer_id,device_id,decrypted_path)
    write_file_to_disk(path_on_server,decrypted_raw_content)

    log_file_info(decrypted_path,device_id,path_on_server)

    with open(path_on_server,'wb') as outfile:
        outfile.write(decrypted_raw_content)

    return path_on_server, device_root_directory_on_server, decrypted_path, len(decrypted_raw_content)

def get_file_name(path_on_server):
    return path_on_server.split("/")[-1]

def get_file_path_without_name(path_on_server):
    return "/".join(path_on_server.split("/")[0:-1]) + "/"

def get_file_type(path_on_server):
    _, file_extension = os.path.splitext(path_on_server)
    return file_extension

def get_server_path(customer_id,device_id,decrypted_path):
    device_root_directory_on_server = "/storage/%s/device/%s/" % (customer_id,device_id)

    print("Combining %s with %s" % (device_root_directory_on_server,decrypted_path))
    if "\\" in decrypted_path:
        # Replace \ with /
        p = pathlib.PureWindowsPath(r'%s'%decrypted_path)
        path = device_root_directory_on_server + str(p.as_posix())

    elif "\\" not in decrypted_path:
        path = device_root_directory_on_server + decrypted_path

    path = path.replace("//","/")
    return path, device_root_directory_on_server

def write_file_to_disk(path,content):
    # TODO: Check if file exists

    # If it does exist, mv original file to rev2 -> move rev2 -> rev3, etc.
    # Find max number of revs and roll off last one
    # make a hidden directory .SCREV/ORIGINAL_NAME.ext.SCREV2
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as outfile:
        outfile.write(content)

def print_request_no_file(request):
    print("== RECEIVED NEW REQUEST ==")
    print("Request type: %s" % request['request_type'])
    print("Agent ID: %s"     % request['agent_id'])
    print("API key: %s\n"    % request['api_key'])

def initialize_logging():
    logging.basicConfig(
            filename='/var/log/stormcloud.log',
            filemode='a',
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG
    )

def log_file_info(decrypted_path,device_id,path_on_server):
    logging.log(logging.INFO,"== STORING FILE : %s ==" % decrypted_path)
    logging.log(logging.INFO,"Device ID:\t%d" % device_id)
    logging.log(logging.INFO,"writing content to %s" % path_on_server)
