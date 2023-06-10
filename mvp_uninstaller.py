import os
import yaml
# import requests
# import subprocess
# import sys
# from win32com.client import Dispatch
# from pathlib import Path


appdata_path = os.getenv('APPDATA') + "\\Stormcloud"

with open(appdata_path + '\\Stormcloud\\stable_settings.yaml', 'r') as file:
    stable_settings = yaml.safe_load(file)

application_path = stable_settings['application_path']

def stop_running_instances():
    # Use taskkill to stop any running instances
    os.system("taskkill /IM stormcloud.exe /F")

# def unregister_device():
    # TODO: Perform unregister operation

def remove_files(application_path, appdata_path):
    os.system(f"rmdir /S /Q {application_path}")
    
    # Uninstall from APPDATA
    if os.path.exists(appdata_path):
        os.system(f"rmdir /S /Q {appdata_path}")

def remove_shortcut():
    # Remove the startup shortcut
    shortcut_path = os.getenv('APPDATA') + "\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Stormcloud.lnk"
    if os.path.exists(shortcut_path):
        os.remove(shortcut_path)

def main():
    stop_running_instances()
    # unregister_device()
    remove_files(application_path, appdata_path)
    remove_shortcut()

if __name__ == "__main__":
    main()