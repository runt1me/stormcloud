import pathlib
import logging
import os
import sys
import glob

import crypto_utils

class ChunkHandler:
    def __init__(self):
        self.active_chunks = []

    def __repr__(self):
        return "ChunkHandler: %s" % self.chunks_in_process

    def __str__(self):
        return "ChunkHandler: %s" % self.chunks_in_process

    def add_active_chunk(self, agent_id, file_path, chunk_index, total_num_chunks, data):
        chunk = (agent_id, file_path, chunk_index, total_num_chunks, data)
        self.active_chunks.append(chunk)

    def combine_chunks(self, agent_id, file_path):
        # Get all chunks that have agent_id and file_path
        # Arrange the byte stream properly and return it
        # NOTE: This O(n) solution is probably not ideal if/when lots of customers involved

        chunks_for_this_file = []
        byte_stream_this_file = ""

        for chunk in self.active_chunks:
            if chunk[0] == agent_id and chunk[1] == file_path:
                print("Found chunk %d for file: %s" % (chunk[2], chunk[1]))
                chunks_for_this_file.append(chunk)

        # Verify that we have all chunks and sort them into the correct order
        if len(chunks_for_this_file) == chunks_for_this_file[0][3]:
            print("Found correct number of chunks")
            # TODO: change this to sort the list based on tuple key... some type of lambda syntax
            # Best for optimization is to choose a sort that works well on mostly already-sorted lists
            sorted_chunks_this_file = chunks_for_this_file

            for chunk in sorted_chunks_this_file:
                # Add the actual data of the chunk to the byte stream
                print(type(chunk[4]))
                byte_stream_this_file += chunk[4]

            # Remove all of these chunks from the active_chunks pile
            self.active_chunks = [c for c in self.active_chunks if c not in sorted_chunks_this_file]

            return byte_stream_this_file

        else:
            # TODO: ???
            # Well in theory this shouldn't happen if I only ack the chunks that I receive properly.
            print("Don't have all chunks for the file yet... what do I do now?")
            return None




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
        if 'file_content' in k or 'chunk' in k:
            continue
        print("%s: %s" % (k,request[k]))

def initialize_logging():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(levelname)-8s %(message)s')
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger

def log_file_info(decrypted_path,device_id,path_on_server):
    logging.log(logging.INFO,"== STORING FILE : %s ==" % decrypted_path)
    logging.log(logging.INFO,"Device ID:\t%d" % device_id)
    logging.log(logging.INFO,"writing content to %s" % path_on_server)
