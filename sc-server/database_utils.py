import mysql.connector
from mysql.connector import Error

import os
import traceback

# REMEMBER TO cnx.commit()!
# ALL SINGLE ARG STORED PROCEDURE CALLS MUST USE (field,) SYNTAX TO INDICATE TUPLE!!

import logging_utils

def __logger__():
    return logging_utils.logger

def passes_sanitize(input_string):
  # Function for validating input to the database.
  # 
  SANITIZE_LIST = ["'", '"', ";", "\\", "--", "*", "%"]
  for expr in SANITIZE_LIST:
    if expr in input_string:
      __logger__().warning("")
      return False

  return True

def update_customer_with_stripe_id(customer_id,stripe_id):
  # IN customer_id INT,
  # IN stripe_id varchar(64)

  ret = []
  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)
  success = False

  try:
    cursor.callproc('uspSaveCustomerStripeID',
      (customer_id,stripe_id)
    )

    for result in cursor.stored_results():
      row = result.fetchall()
      ret.append(row)

    if ret[0][0][0] == 1:
      success = True
    elif ret[0][0][0] == -1:
      success = False

  except Error as e:
    __logger__().error(e)

  finally:
    cnx.commit()
    __teardown__(cursor,cnx)
    return success

def update_callback_for_device(device_id, callback_time, status_code):
  # IN DID INT, IN callback_time varchar(512), IN device_status INT
  ret = []
  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('update_callback_for_device',
      (device_id, callback_time, status_code)
    )

    for result in cursor.stored_results():
      row = result.fetchall()
      ret.append(row)

  except Error as e:
    __logger__().error(e)

  finally:
    cnx.commit()
    __teardown__(cursor,cnx)
    return ret

def add_or_update_customer(customer_name,customer_email,customer_guid,plan,api_key):
  # IN customer_name varchar(256),
  # IN customer_email varchar(256),
  # IN customer_guid varchar(64),
  # IN plan varchar(64),
  # IN api_key varchar(64)

  ret = []
  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('add_or_update_customer',
      (customer_name,customer_email,customer_guid,plan,api_key)
    )

    for result in cursor.stored_results():
      row = result.fetchall()
      ret.append(row)

  except Error as e:
    __logger__().error(e)

  finally:
    cnx.commit()
    __teardown__(cursor,cnx)
    return ret

def add_or_update_file_for_device(device_id, file_name, file_path, client_full_name_and_path, client_full_name_and_path_as_posix, client_directory_as_posix, file_size, file_type, stormcloud_full_name_and_path):
  # IN DID INT,
  # IN file_name varchar(512),
  # IN file_path varchar(1024),
  # IN client_full_name_and_path varchar(1024),
  # IN path_on_device_posix varchar(1024),
  # IN file_size int,
  # IN file_type varchar(256),
  # IN stormcloud_full_name_and_path varchar(1024)

  ret = []
  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('add_or_update_file_for_device',(
          device_id,
          file_name,
          file_path,
          client_full_name_and_path,
          client_full_name_and_path_as_posix,
          client_directory_as_posix,
          file_size,
          file_type,
          stormcloud_full_name_and_path
    ))

    for result in cursor.stored_results():
      row = result.fetchall()
      ret.append(row)

  except Error as e:
    __logger__().error(e)

  finally:
    cnx.commit()
    __teardown__(cursor,cnx)
    return ret

def add_or_update_device_for_customer(customer_id, device_name, device_type, ip_address, operating_system, device_status, last_callback, stormcloud_path_to_secret_key, agent_id):
  # IN CID INT,
  # IN device_name varchar(512),
  # IN device_type varchar(512),
  # IN ip_address varchar(256),
  # IN operating_system varchar(512),
  # IN device_status INT,
  # IN last_callback varchar(512),
  # IN stormcloud_path_to_secret_key varchar(1024)
  # IN agent_id varchar(256)

  ret = []
  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('add_or_update_device_for_customer',
      (customer_id, device_name, device_type, ip_address, operating_system, device_status, last_callback, stormcloud_path_to_secret_key, agent_id)
    )

    for result in cursor.stored_results():
        row = result.fetchall()
        ret.append(row)

  except Error as e:
    __logger__().error(e)

  finally:
    cnx.commit()
    __teardown__(cursor,cnx)
    return ret

def add_file_to_restore_queue(agent_id, file_path):
    # IN agent_id varchar(256),
    # IN ClientFullNameAndPathAsPosix varchar(1024)
    ret = []

    cnx = __connect_to_db__()
    cursor = cnx.cursor(buffered=True)

    file_object_id = -1
    affected = 0
    try:
        __logger__().info("CALL get_file_object_id('%s','%s');" % (agent_id,file_path))
        cursor.callproc('get_file_object_id',
            (agent_id,file_path)
        )

        for result in cursor.stored_results():
            row = result.fetchall()

        if row:
            file_object_id = row[0]
        else:
            raise Exception("Did not get a valid file_object_id for agent_id and file_path combination.")

        literal_file_object_id = file_object_id[0]
        __logger__().info("CALL add_file_to_restore_queue('%s');" % file_object_id)

        cursor.callproc('add_file_to_restore_queue',
            (literal_file_object_id,)
        )

        affected = cursor.rowcount
        print("Rows affected: %d" % affected)
        affected = 1
    except Exception as e:
        __logger__().error(traceback.format_exc())
    finally:
        cnx.commit()
        __teardown__(cursor,cnx)
        return affected

def get_list_of_files_to_restore(device_id):
    # IN device_id INT
    ret = []

    cnx = __connect_to_db__()
    cursor = cnx.cursor(buffered=True)

    try:
        cursor.callproc('get_list_of_files_to_restore', (device_id,))

        for result in cursor.stored_results():
            row = result.fetchall()
            ret.append(row)

        if not ret:
            return []

    except Exception as e:
        __logger__().error("Got exception in get_list_of_files_to_restore: %s" %traceback.format_exc())
    finally:
        __teardown__(cursor,cnx)
        return ret[0]

def get_server_path_for_file(device_id, file_path):
  # IN device_id INT
  # IN file_path varchar(255)
  
  ret = []
  server_path = ""

  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)
  __logger__().info("CALL get_server_path_for_file('%d','%s');" % (device_id,file_path))

  try:
    cursor.callproc('get_server_path_for_file', (device_id, file_path))

    for result in cursor.stored_results():
      row = result.fetchall()

      if row:
        server_path = row[0][0]
      else:
        raise Exception("Failed to get server path for file requested from client: %s" % file_path)

  except Exception as e:
    __logger__().error("Got exception in get_server_path_for_file: %s" %traceback.format_exc())
  finally:
    __teardown__(cursor,cnx)
    return server_path

def mark_file_as_restored(device_id, file_path):
  # IN device_id INT
  # IN file_path varchar(255)
  
  ret = []

  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)
  __logger__().info("Calling mark_file_as_restored(%d,%s)" % (device_id,file_path))

  try:
    cursor.callproc('mark_file_as_restored', (device_id, file_path))
    affected = cursor.rowcount

    __logger__().info("Rows affected: %s" % affected)

  except Exception as e:
    __logger__().error("Got exception in mark_file_as_restored: %s" %traceback.format_exc())
  finally:
    cnx.commit()
    __teardown__(cursor,cnx)
    return ret

def get_last_10_callbacks_for_device(device_ip,device_name):
  # TODO: change this to use get_device_by_agent_id
  ret = []

  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  device_id = -1
  try:
    cursor.callproc('get_device_id_by_ipaddress_and_name',
      (device_ip,device_name)
    )

    for result in cursor.stored_results():
        row = result.fetchall()
        device_id = row[0]

    cursor.callproc('get_last_10_callbacks_for_device',
      (device_id,)
    )

    for result in cursor.stored_results():
      row = result.fetchall()
      ret.append(row)

  except Error as e:
    __logger__().error(e)

  finally:
    __teardown__(cursor,cnx)
    return ret

def get_next_device_id():
    ret = []

    cnx = __connect_to_db__()
    cursor = cnx.cursor(buffered=True)

    try:
        cursor.callproc('get_next_device_id', ())

        for result in cursor.stored_results():
            # Comes back as a list of tuples, hence row[0][0]
            row = result.fetchall()
            highest_device_id = row[0][0]

        ret = int(highest_device_id)

    except Error as e:
        __logger__().error(e)

    finally:
        __teardown__(cursor,cnx)
        return ret

def get_next_customer_id():
    ret = []

    cnx = __connect_to_db__()
    cursor = cnx.cursor(buffered=True)

    try:
        cursor.callproc('get_next_customer_id', ())

        for result in cursor.stored_results():
            # Comes back as a list of tuples, hence row[0][0]
            row = result.fetchall()
            highest_customer_id = row[0][0]

        ret = int(highest_customer_id)

    except Error as e:
        __logger__().error(e)

    finally:
        __teardown__(cursor,cnx)
        return ret

def get_customer_id_by_api_key(api_key):
  ret = []

  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  customer_id = -1
  try:
    cursor.callproc('get_customer_id_by_api_key', (api_key,))

    for result in cursor.stored_results():
        row = result.fetchall()
        customer_id = row[0][0]

        ret = customer_id

  except Error as e:
    __logger__().error(e)

  finally:
    __teardown__(cursor,cnx)
    return ret

def get_device_by_agent_id(agent_id):
  ret = []

  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('get_device_by_agent_id', (agent_id,))

    for result in cursor.stored_results():
        row = result.fetchall()
        ret = row[0]

  except Error as e:
    __logger__().error(e)

  finally:
    __teardown__(cursor,cnx)
    return ret

def is_api_key_superuser(api_key):
  ret = []

  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('is_api_key_superuser', (api_key,))

    for result in cursor.stored_results():
        row = result.fetchall()
        ret = row[0][0]

  except Error as e:
    __logger__().error(e)

  finally:
    __teardown__(cursor,cnx)
    if ret:
      return True
    else:
      return False

def get_api_key_status(api_key):
  ret = []

  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('get_api_key_status', (api_key,))

    for result in cursor.stored_results():
        row = result.fetchall()
        ret = row[0][0]

  except Error as e:
    __logger__().error(e)

  finally:
    __teardown__(cursor,cnx)
    if ret == -1:
      return "API_KEY_DOES_NOT_EXIST"
    elif ret == 0:
      return "API_KEY_INACTIVE"
    elif ret == 1:
      return "API_KEY_ACTIVE"
    else:
      # This shouldn't happen
      return "API_KEY_UNKNOWN"

def add_daily_disk_usage(customer_id, disk_usage_in_gb):
  """
    Adds an entry into disk usage table for the given customer
  """
  success = False

  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  disk_usage_in_gb = float(disk_usage_in_gb)

  # Normalize to 2 decimal places
  disk_usage_in_gb = round(disk_usage_in_gb, 2)

  try:
    cursor.callproc('add_daily_disk_usage', (customer_id,disk_usage_in_gb))
    success = True

  except Error as e:
    __logger__().error(e)
    success = False

  finally:
    cnx.commit()
    __teardown__(cursor,cnx)

    return success

def get_monthly_average_disk_usage(customer_id):
  """
    Gets average disk usage for customer_id for current month
  """
  ret = []

  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('calculate_monthly_average_disk_usage', (customer_id,))

    for result in cursor.stored_results():
        row = result.fetchall()
        print(row)

        ret = row[0][0]

  except Error as e:
    __logger__().error(e)

  finally:
    __teardown__(cursor,cnx)
    if ret:
      return ret
    else:
      return False

def get_billing_amount(customer_id):
  """
    Get billing amount for the given customer
  """
  ret = []

  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('calculate_total_bill', (customer_id,))

    for result in cursor.stored_results():
        row = result.fetchall()
        print(row)

        ret = row[0][0]

  except Error as e:
    __logger__().error(e)

  finally:
    __teardown__(cursor,cnx)
    if ret:
      return ret
    else:
      return False

def __connect_to_db__():
  mysql_username = os.getenv('MYSQLUSER')
  mysql_password = os.getenv('MYSQLPASSWORD')
  mysql_db_name  = os.getenv('MYSQLDBNAME')
  mysql_db_host  = os.getenv('MYSQLHOST')
  mysql_db_port  = os.getenv('MYSQLPORT')

  return mysql.connector.connect(
          user=mysql_username,
          password=mysql_password,
          database=mysql_db_name,
          host=mysql_db_host,
          port=mysql_db_port
         )

def __teardown__(cursor,cnx):
  if cnx.is_connected():
    cursor.close()
    cnx.close()
