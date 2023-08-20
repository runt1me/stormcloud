import os
import yaml
import subprocess
import sys
import winreg

from pathlib import Path

appdata_path = os.getenv('APPDATA')
sc_appdata_path = appdata_path + "\\Stormcloud"

with open(sc_appdata_path + '\\Stormcloud\\stable_settings.yaml', 'r') as file:
    stable_settings = yaml.safe_load(file)

application_path = stable_settings['application_path']

def stop_running_instances():
    os.system("taskkill /IM stormcloud.exe /F")

def unregister_app(app_name):
    try:
        key_path = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
        
        # Check if the key exists, and if so, delete it
        with winreg.OpenKey(key, app_name, 0, winreg.KEY_ALL_ACCESS) as subkey:
            winreg.DeleteKey(key, app_name)
        
        winreg.CloseKey(key)
    except FileNotFoundError:
        print(f"Application {app_name} not found in registry.")
    except Exception as e:
        print(f"An error occurred while attempting to unregister the application: {e}")

def remove_shortcut():
    shortcut_path = os.getenv('APPDATA') + "\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\Stormcloud.lnk"
    if os.path.exists(shortcut_path):
        os.remove(shortcut_path)

def remove_files(application_path, sc_appdata_path):
    if application_path != sc_appdata_path: # Removal of AppData\Roaming\Stormcloud is handled separately
        os.system(f"rmdir /S /Q {application_path}")

def create_self_destruct_batch(appdata_path, sc_appdata_path):
    bat_path = os.path.join(appdata_path, "delete_uninstaller.bat")
    max_retries = 10
    with open(bat_path, 'w') as bat_file:
        bat_file.write(f"set retries=0\n")
        bat_file.write(f":wait\n")
        bat_file.write(f"timeout /t 2 > NUL\n") # Wait for 2 seconds
        bat_file.write(f"del \"{sys.executable}\" > NUL\n")
        bat_file.write(f"if exist \"{sys.executable}\" (\n")
        bat_file.write(f"    set /a retries+=1\n")
        bat_file.write(f"    if %retries% lss {max_retries} (\n")
        bat_file.write(f"        goto wait\n")
        bat_file.write(f"    ) else (\n")
        bat_file.write(f"        echo Unable to delete uninstaller after {max_retries} retries. Please delete it manually.\n")
        bat_file.write(f"        pause\n")
        bat_file.write(f"        exit\n")
        bat_file.write(f"    )\n")
        bat_file.write(f")\n")
        bat_file.write(f"rmdir /S /Q \"{sc_appdata_path}\" > NUL\n") # Safely delete the sc_appdata_path folder
        bat_file.write(f"del \"{bat_path}\" > NUL\n") # Delete the batch file itself
    subprocess.Popen([bat_path], shell=True)


def main():
    stop_running_instances()
    unregister_app('Stormcloud')
    remove_shortcut()
    remove_files(application_path = application_path
                 , sc_appdata_path = sc_appdata_path)
    create_self_destruct_batch(appdata_path = appdata_path
                               , sc_appdata_path = sc_appdata_path)

if __name__ == "__main__":
    main()