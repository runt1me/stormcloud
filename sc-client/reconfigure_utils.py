import os
import json
import logging
import yaml

import requests
import pdb

import crypto_utils
import network_utils as scnet

from time import sleep

def fetch_and_update_backup_paths(settings_file_path, api_key, agent_id, interval=30):
    while True:
        url = "https://apps.darkage.io/darkage/api/fetch_backup_folders.cfm"
        headers = {"Content-Type": "application/json"}
        data = {"api_key": api_key, "agent_id": agent_id}

        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                result = response.json()
                
                if result.get('SUCCESS'):
                    columns_list = result['DATA']['COLUMNS']
                    data = result['DATA']['DATA']

                    # pdb.set_trace()
                    backup_paths = [row[columns_list.index("FOLDER_PATH")] for row in data if row[columns_list.index("IS_RECURSIVE")] == 0]
                    recursive_backup_paths = [row[columns_list.index("FOLDER_PATH")] for row in data if row[columns_list.index("IS_RECURSIVE")] == 1]

                    settings = yaml.safe_load(open(settings_file_path, 'r'))
                    settings['BACKUP_PATHS'] = backup_paths
                    settings['RECURSIVE_BACKUP_PATHS'] = recursive_backup_paths

                    with open(settings_file_path, 'w') as settings_file:
                        yaml.dump(settings, settings_file)

                else:
                    print(f"Error: {result.get('message')}")
            else:
                print(f"Failed to fetch folder data. Status code: {response.status_code}")
        except Exception as e:
            print(f"Exception occurred: {e}")

        sleep(interval)
