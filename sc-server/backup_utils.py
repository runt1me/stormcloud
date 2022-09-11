import pathlib
import logging
import os
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
    original_file_name  = get_file_name(path)
    if os.path.exists(path):
        print("Maximum number of versions stored: %d" % max_versions)

        sc_version_directory = os.path.dirname(path) + "/.SCVERS/"

        print("Looking for versions at path: %s" % sc_version_directory)
        os.makedirs(os.path.dirname(sc_version_directory), exist_ok=True)

        # List all files in path that match *filename* = all versions of the file
        file_name = get_file_name(path)
        print("Checking in %s for matches *%s*" % (sc_version_directory,file_name))
        match = glob.glob(sc_version_directory+"*%s*" % file_name)

        if match:
            print("Found matches:" %match)
            match.sort()
            match.reverse()
            print("match list (reverse sorted) %s" %match)
            # sort list to descending order (5,4,3,2)
            # move 5 -> 6
            # move 4 -> 5
            # move 3 -> 4
            # move 2 -> 3
            # move current -> 2
            for m in match:
                file_name = get_file_name(m)
                print("Looking at filename: %s" %file_name)

                # get the thing from after the last occurrence of .SCVER
                version = int(file_name.split(".SCVER")[-1])
                next_version = version + 1

                string_to_replace   = ".SCVER%d"%version
                replacement_string  = ".SCVER%d"%next_version

                print("== Renaming ==")
                print(m)
                print(m.replace(string_to_replace,replacement_string))

                os.rename(m,m.replace(string_to_replace,replacement_string))

        print("Creating ver2")
        # copy original path to VER2
        old_version_full_path = sc_version_directory + original_file_name + ".SCVER2"
        os.rename(path,old_version_full_path)

    # Finally, write the original content at the originally specified file path
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
