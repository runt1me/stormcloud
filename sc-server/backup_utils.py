import pathlib
import logging_utils
import os
import sys
import glob

def __logger__():
    return logging_utils.logger

def get_file_name(path_on_server):
    return path_on_server.split("/")[-1]

def get_file_path_without_name(path_on_server):
    return "/".join(path_on_server.split("/")[0:-1]) + "/"

def get_file_type(path_on_server):
    _, file_extension = os.path.splitext(path_on_server)
    return file_extension

def get_server_path(customer_id,device_id,decrypted_path):
    device_root_directory_on_server = "/storage/%s/device/%s/" % (customer_id,device_id)

    __logger__().info("Combining %s with %s" % (device_root_directory_on_server,decrypted_path))
    if "\\" in decrypted_path:
        # Replace \ with /
        p = pathlib.PureWindowsPath(r'%s'%decrypted_path)
        path = device_root_directory_on_server + str(p.as_posix())

    elif "\\" not in decrypted_path:
        path = device_root_directory_on_server + decrypted_path

    path = path.replace("//","/")
    return path, device_root_directory_on_server

def stream_write_file_to_disk(path,file_handle,max_versions,chunk_size):
    if os.path.exists(path):
        handle_versions(path, max_versions)

    __logger__().info("Stream writing file to disk: %s   %s   %s   %s" % (path,file_handle,max_versions,chunk_size))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'ab') as target_file:
        while True:
            chunk = file_handle.read(chunk_size)
            if not chunk:
                break

            __logger__().info("got a chunk of %s" % path)
            target_file.write(chunk)

    return os.path.getsize(path)

def handle_versions(path,max_versions):
    original_file_name = get_file_name(path)
    sc_version_directory = os.path.dirname(path) + "/.SCVERS/"

    __logger__().info("Maximum number of versions stored: %d" % max_versions)

    os.makedirs(os.path.dirname(sc_version_directory), exist_ok=True)

    __logger__().info("Checking in %s for matches %s.SCVER[0-9]*" % (sc_version_directory,original_file_name))
    match = glob.glob(sc_version_directory+"%s.SCVER[0-9]*" % original_file_name)
    __logger__().info("Got match: %s" % match)

    if match:
        match.sort(reverse=True)

        for m in match:
            fn = get_file_name(m)

            # get the thing from after the last occurrence of .SCVER
            version = int(fn.split(".SCVER")[-1])
            next_version = version + 1

            if next_version > max_versions:
                __logger__().info("Device has reached the max # of versions for file.")
                __logger__().info("Not processing version: %d" %next_version)
                continue

            string_to_replace   = ".SCVER%d"%version
            replacement_string  = ".SCVER%d"%next_version

            print_rename(m,m.replace(string_to_replace,replacement_string))
            os.rename(m,m.replace(string_to_replace,replacement_string))

    old_version_full_path = sc_version_directory + original_file_name + ".SCVER2"

    print_rename(path,old_version_full_path)
    os.rename(path,old_version_full_path)

def print_rename(old,new):
    __logger__().info("== RENAMING ==")
    __logger__().info(old)
    __logger__().info(new)

def print_request_no_file(request):
    __logger__().info("== RECEIVED NEW REQUEST ==")
    for k in request.keys():
        if 'file_content' in k or 'chunk' in k:
            continue
        __logger__().info("%s: %s" % (k,request[k]))

def log_file_info(decrypted_path,device_id,path_on_server):
    __logger__().info("== STORING FILE : %s ==" % decrypted_path)
    __logger__().info("Device ID:\t%d" % device_id)
    __logger__().info("writing content to %s" % path_on_server)
