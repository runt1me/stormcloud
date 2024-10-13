import os
import sys
import json
import shutil
import logging
import winreg
import subprocess
import psutil
import time
from pathlib import Path

def setup_logging():
    log_path = os.path.join(os.getenv('TEMP'), 'stormcloud_uninstall.log')
    logging.basicConfig(filename=log_path, level=logging.INFO, 
                        format='%(asctime)s - %(levelname)s - %(message)s')

def get_install_path():
    appdata_path = os.getenv('APPDATA')
    stable_settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
    
    if not os.path.exists(stable_settings_path):
        logging.error("stable_settings.cfg not found")
        return None

    with open(stable_settings_path, 'r') as f:
        settings = json.load(f)

    return settings.get('install_path')

def terminate_stormcloud_processes():
    terminated = False
    for proc in psutil.process_iter(['name', 'exe']):
        try:
            if proc.name().lower() == 'stormcloud.exe' or (proc.exe() and 'stormcloud' in proc.exe().lower()):
                proc.terminate()
                logging.info(f"Terminated Stormcloud process: {proc.pid}")
                terminated = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if terminated:
        time.sleep(2)
        for proc in psutil.process_iter(['name', 'exe']):
            try:
                if proc.name().lower() == 'stormcloud.exe' or (proc.exe() and 'stormcloud' in proc.exe().lower()):
                    proc.kill()
                    logging.info(f"Force killed Stormcloud process: {proc.pid}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

    return terminated

def remove_stormcloud_folder(install_path):
    if not install_path or not os.path.exists(install_path):
        logging.error(f"Invalid installation path: {install_path}")
        return False

    try:
        shutil.rmtree(install_path)
        logging.info(f"Removed Stormcloud installation folder: {install_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to remove Stormcloud installation folder: {str(e)}")
        return False

def remove_appdata_files():
    appdata_path = os.getenv('APPDATA')
    stormcloud_appdata_folder = os.path.join(appdata_path, 'Stormcloud')
    
    try:
        if os.path.exists(stormcloud_appdata_folder):
            shutil.rmtree(stormcloud_appdata_folder)
            logging.info(f"Removed Stormcloud folder from AppData: {stormcloud_appdata_folder}")
        else:
            logging.info("Stormcloud folder not found in AppData")
        return True
    except Exception as e:
        logging.error(f"Failed to remove Stormcloud folder from AppData: {str(e)}")
        return False

def remove_shortcut_and_startup():
    try:
        # Remove shortcut from Start Menu
        start_menu_programs = os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows', 'Start Menu', 'Programs')
        stormcloud_folder = os.path.join(start_menu_programs, 'Stormcloud')
        if os.path.exists(stormcloud_folder):
            shutil.rmtree(stormcloud_folder)
            logging.info(f"Removed Stormcloud folder from Start Menu: {stormcloud_folder}")
        else:
            logging.info("Stormcloud folder not found in Start Menu")

        # Remove from startup (registry)
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            winreg.DeleteValue(key, "Stormcloud Backup Engine")
            winreg.CloseKey(key)
            logging.info("Removed Stormcloud from startup registry")
        except WindowsError as e:
            if e.winerror == 2:  # The system cannot find the file specified
                logging.info("Stormcloud was not found in startup registry")
            else:
                raise

        return True
    except Exception as e:
        logging.error(f"Failed to remove shortcut or startup entry: {str(e)}")
        return False

def remove_registry_entries():
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Stormcloud"
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        logging.info("Removed registry entries")
    except WindowsError as e:
        if e.winerror == 2:  # The system cannot find the file specified
            logging.info("Stormcloud registry key was not found")
        else:
            logging.error(f"Failed to remove registry entries: {str(e)}")

def self_remove(install_path):
    batch_path = os.path.join(os.getenv('TEMP'), 'remove_stormcloud.bat')
    with open(batch_path, 'w') as batch_file:
        batch_file.write('@echo off\n')
        batch_file.write('timeout /t 1 /nobreak >nul\n')
        batch_file.write(f'del "{sys.executable}"\n')
        batch_file.write(f'del "{os.path.join(install_path, "stable_settings.cfg")}"\n')
        batch_file.write(f'rmdir /s /q "{install_path}"\n')
        batch_file.write(f'del "%~f0"\n')

    subprocess.Popen(batch_path, creationflags=subprocess.CREATE_NO_WINDOW)

def main():
    setup_logging()
    
    logging.info("Starting Stormcloud uninstallation")

    if terminate_stormcloud_processes():
        logging.info("Terminated running Stormcloud processes")
    else:
        logging.info("No running Stormcloud processes found")

    install_path = get_install_path()
    if install_path:
        remove_stormcloud_folder(install_path)
    else:
        logging.warning("Could not determine installation path, skipping removal of installation folder")

    remove_appdata_files()
    remove_shortcut_and_startup()
    remove_registry_entries()

    logging.info("Stormcloud uninstallation completed")

if __name__ == "__main__":
    main()