import logging

import database_utils as db

def record_keepalive(device_id,current_time):
    logging.log(logging.INFO,"recording keepalive for device %d" %device_id)
    ret = db.update_callback_for_device(device_id,current_time,0)

    return ret

def get_keepalive_response_data(device_id):
    file_list_tuples = db.get_list_of_files_to_restore(device_id)
    print(file_list_tuples)
    file_names = [i[1] for i in file_list_tuples]
    print(file_names)

    data_dict = {
        "restore_queue": file_names
    }

    return data_dict
