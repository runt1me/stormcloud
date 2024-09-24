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
            # Check if the process name is 'stormcloud.exe' or if the executable path contains 'Stormcloud'
            if proc.name().lower() == 'stormcloud.exe' or (proc.exe() and 'stormcloud' in proc.exe().lower()):
                proc.terminate()
                logging.info(f"Terminated Stormcloud process: {proc.pid}")
                terminated = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if terminated:
        # Give some time for the processes to terminate
        time.sleep(2)
        
        # Check if any processes are still running and force kill if necessary
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

    # Ensure the bottom-level folder is named "Stormcloud"
    if os.path.basename(install_path.rstrip('\\')) != "Stormcloud":
        logging.error(f"Installation path does not end with 'Stormcloud': {install_path}")
        return False

    try:
        # Remove all files except the uninstaller
        for item in os.listdir(install_path):
            item_path = os.path.join(install_path, item)
            if item_path != sys.executable and item != 'stable_settings.cfg':
                if os.path.isfile(item_path):
                    os.unlink(item_path)
                    logging.info(f"Removed file: {item_path}")
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    logging.info(f"Removed directory: {item_path}")

        logging.info(f"Removed Stormcloud folder contents: {install_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to remove Stormcloud folder contents: {str(e)}")
        return False

def remove_startup_entry():
    startup_folder = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
    shortcut_path = os.path.join(startup_folder, 'Stormcloud Backup Engine.lnk')

    if os.path.exists(shortcut_path):
        try:
            os.remove(shortcut_path)
            logging.info(f"Removed startup shortcut: {shortcut_path}")
        except Exception as e:
            logging.error(f"Failed to remove startup shortcut {shortcut_path}: {str(e)}")

def remove_registry_entries():
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Stormcloud")
        logging.info("Removed registry entries")
    except WindowsError as e:
        logging.error(f"Failed to remove registry entries: {str(e)}")

def self_remove(install_path):
    # Create a batch file to remove the uninstaller, the Stormcloud folder, and stable_settings.cfg
    batch_path = os.path.join(os.getenv('TEMP'), 'remove_stormcloud.bat')
    with open(batch_path, 'w') as batch_file:
        batch_file.write('@echo off\n')
        batch_file.write('timeout /t 1 /nobreak >nul\n')  # Wait for 1 second
        batch_file.write(f'del "{sys.executable}"\n')
        batch_file.write(f'del "{os.path.join(install_path, "stable_settings.cfg")}"\n')
        batch_file.write(f'rmdir /s /q "{install_path}"\n')
        batch_file.write(f'del "%~f0"\n')  # Self-delete the batch file

    # Run the batch file
    subprocess.Popen(batch_path, creationflags=subprocess.CREATE_NO_WINDOW)

def main():
    setup_logging()
    
    logging.info("Starting Stormcloud uninstallation")

    # Terminate any running Stormcloud processes
    if terminate_stormcloud_processes():
        logging.info("Terminated running Stormcloud processes")
    else:
        logging.info("No running Stormcloud processes found")

    install_path = get_install_path()
    if not install_path:
        logging.error("Uninstallation failed: Could not determine installation path")
        return

    if remove_stormcloud_folder(install_path):
        remove_startup_entry()
        remove_registry_entries()

        logging.info("Stormcloud uninstallation completed")

        # Self-remove
        self_remove(install_path)
    else:
        logging.error("Uninstallation failed: Could not remove Stormcloud folder")

if __name__ == "__main__":
    main()
