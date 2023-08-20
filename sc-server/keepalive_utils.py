import database_utils as db
import logging_utils

def __logger__():
    return logging_utils.logger

def record_keepalive(device_id,current_time):
    __logger__().info("recording keepalive for device %d" %device_id)
    ret = db.update_callback_for_device(device_id,current_time,0)

    return ret

def get_keepalive_response_data(device_id):
    file_list_tuples = db.get_list_of_files_to_restore(device_id)
    file_names = [i[1] for i in file_list_tuples]

    data_dict = {
        "restore_queue": file_names
    }

    return data_dict
