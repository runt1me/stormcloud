import mysql.connector
from mysql.connector import Error

import os

# REMEMBER TO cnx.commit()!

def run():
  print(get_last_10_callbacks_for_device("212.100.134.11","web1.njsd.k12.wi.us"))

def get_last_10_callbacks_for_device(device_ip,device_name):
  ret = []

  cnx = connect_to_db()
  cursor = cnx.cursor(buffered=True)

  device_id = -1
  # get device ID by ip/name, then get callbacks
  try:
    query_get_deviceid_args = (device_ip,device_name)
    cursor.callproc('get_device_id_by_ipaddress_and_name',
      query_get_deviceid_args
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
    if cnx.is_connected():
      cursor.close()
      cnx.close()
      print("closed cnx")
      return ret

def connect_to_db():
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
