import mysql.connector
from mysql.connector import Error

import os

# REMEMBER TO cnx.commit()!

def passes_sanitize(input_string):
  SANITIZE_LIST = ["'", '"', ";"]
  for expr in SANITIZE_LIST:
    if expr in input_string:
      return False

  return True

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
    print(e)

  finally:
    cnx.commit()
    __teardown__(cursor,cnx)
    return ret

def add_or_update_customer(customer_name,username,password,api_key):
  # IN customer_name varchar(256),
  # IN username varchar(256),
  # IN password varchar(256),
  # IN api_key varchar(64)

  ret = []
  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('add_or_update_customer',
      (customer_name,username,password,api_key)
    )

    for result in cursor.stored_results():
      row = result.fetchall()
      ret.append(row)

  except Error as e:
    print(e)

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
    print(e)

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
    print("Error: %s" %e)

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
    try:
        cursor.callproc('get_file_object_id',
            (agent_id,file_path)
        )

        for result in cursor.stored_results():
            row = result.fetchall()
            file_object_id = row[0]

        if file_object_id == -1:
            raise Exception("Did not get a valid file_object_id for agent_id and file_path combination.")

        cursor.callproc('add_file_to_restore_queue',
            (file_object_id)
        )

        affected = cursor.rowcount            
    except Error as e:
        print(e)
    finally:
        cnx.commit()
        __teardown__(cursor,cnx)
        return affected

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
      (device_id)
    )

    for result in cursor.stored_results():
      row = result.fetchall()
      ret.append(row)

  except Error as e:
    print(e)

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
        print(e)

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
        print(e)

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
    print(e)

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
    print(e)

  finally:
    __teardown__(cursor,cnx)
    return ret

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
