import pathlib
import logging
import os
import sys
import glob

import crypto_utils

def store_file(customer_id,device_id,path_to_device_secret_key,file_path,file_raw_content,max_versions):
    decrypted_raw_content, _ = crypto_utils.decrypt_msg(path_to_device_secret_key,file_raw_content,decode=False)
    decrypted_path, _        = crypto_utils.decrypt_msg(path_to_device_secret_key,file_path,decode=True)

    path_on_server, device_root_directory_on_server = get_server_path(customer_id,device_id,decrypted_path)
    write_file_to_disk(path_on_server,decrypted_raw_content,max_versions)

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

def write_file_to_disk(path,content,max_versions):
    if os.path.exists(path):
        handle_versions(path,max_versions)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as outfile:
        outfile.write(content)

def handle_versions(path,max_versions):
    original_file_name = get_file_name(path)
    sc_version_directory = os.path.dirname(path) + "/.SCVERS/"

    print("Maximum number of versions stored: %d" % max_versions)

    os.makedirs(os.path.dirname(sc_version_directory), exist_ok=True)

    print("Checking in %s for matches %s.SCVER[0-9]*" % (sc_version_directory,original_file_name))
    match = glob.glob(sc_version_directory+"%s.SCVER[0-9]*" % original_file_name)
    print("Got match: %s" % match)

    if match:
        match.sort(reverse=True)

        for m in match:
            fn = get_file_name(m)

            # get the thing from after the last occurrence of .SCVER
            version = int(fn.split(".SCVER")[-1])
            next_version = version + 1

            if next_version > max_versions:
                print("Device has reached the max # of versions for file.")
                print("Not processing version: %d" %next_version)
                continue

            string_to_replace   = ".SCVER%d"%version
            replacement_string  = ".SCVER%d"%next_version

            print_rename(m,m.replace(string_to_replace,replacement_string))
            os.rename(m,m.replace(string_to_replace,replacement_string))

    old_version_full_path = sc_version_directory + original_file_name + ".SCVER2"

    print_rename(path,old_version_full_path)
    os.rename(path,old_version_full_path)

def print_rename(old,new):
    print("== RENAMING ==")
    print(old)
    print(new)

def print_request_no_file(request):
    print("== RECEIVED NEW REQUEST ==")
    for k in request.keys():
        if 'file_content' in k:
            continue
        print("%s: %s" % (k,request[k]))

def initialize_logging():
    logging.basicConfig(
            stream=sys.stdout,
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG
    )

def log_file_info(decrypted_path,device_id,path_on_server):
    logging.log(logging.INFO,"== STORING FILE : %s ==" % decrypted_path)
    logging.log(logging.INFO,"Device ID:\t%d" % device_id)
    logging.log(logging.INFO,"writing content to %s" % path_on_server)
