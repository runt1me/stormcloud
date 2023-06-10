import os
# import requests
# import subprocess
# import sys
# from win32com.client import Dispatch
# from pathlib import Path

app_path = os.getenv('APPDATA') + "\\Stormcloud"

def stop_running_instances():
    # Use taskkill to stop any running instances
    os.system("taskkill /IM stormcloud.exe /F")

# def unregister_device():
    # TODO: Perform unregister operation

def remove_files(app_path):
    # Remove the application directory
    install_directory = app_path
    os.system(f"rmdir /S /Q {install_directory}")
    
    # Uninstall from APPDATA
    appdata_path = os.getenv('APPDATA') + "\\Stormcloud"
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
    remove_files(app_path)
    remove_shortcut()

if __name__ == "__main__":
    main()