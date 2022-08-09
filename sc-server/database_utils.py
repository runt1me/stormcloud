import mysql.connector
from mysql.connector import Error

import os

# REMEMBER TO cnx.commit()!

def run():
  # Worked as of 1/3/2022
  print("update_callback_for_device(1,'2022-01-03 10:52:00',0)")
  print(update_callback_for_device(1,'2022-01-03 10:52:00',0))
  print("add_or_update_file_for_device(1,'foo.txt','C:\\','C:\\foo.txt',11,'txt','/storage/1/foo.txt')")
  print(add_or_update_file_for_device(1,'foo.txt','C:\\','C:\\foo.txt',11,'txt','/storage/1/foo.txt'))
  print("add_or_update_device_for_customer(1,'important.server.com','important server','123.234.123.234','Windows 10 Pro',0,'2021-01-03 10:55:00')")
  print(add_or_update_device_for_customer(1,'important.server.com','important server','123.234.123.234','Windows 10 Pro',0,'2021-01-03 10:55:00','/keys/105/secret.key'))

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

def add_or_update_customer_for_team(customer_name,username,password,team_id,api_key):
  # IN customer_name varchar(256),
  # IN username varchar(256),
  # IN password varchar(256),
  # IN team_id int,
  # IN api_key varchar(64)

  ret = []
  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('add_or_update_customer_for_team',
      (customer_name,username,password,team_id,api_key)
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

def add_or_update_file_for_device(device_id, file_name, file_path, client_full_name_and_path, file_size, file_type, stormcloud_full_name_and_path):
  # IN DID INT,
  # IN file_name varchar(512),
  # IN file_path varchar(1024),
  # IN client_full_name_and_path varchar(1024),
  # IN file_size int,
  # IN file_type varchar(256),
  # IN stormcloud_full_name_and_path varchar(1024)

  ret = []
  cnx = __connect_to_db__()
  cursor = cnx.cursor(buffered=True)

  try:
    cursor.callproc('add_or_update_file_for_device',
      (device_id,file_name,file_path,client_full_name_and_path,file_size,file_type,stormcloud_full_name_and_path)
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

def get_last_10_callbacks_for_device(device_ip,device_name):
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
