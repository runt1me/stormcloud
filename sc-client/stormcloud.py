import calendar
import time
from time import sleep
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict
import argparse
import pathlib
import os
import json
import traceback

import sqlite3
import yaml

import threading
import logging

# import sslkeylog

import keepalive_utils
import backup_utils
import logging_utils
import reconfigure_utils
import network_utils

from infi.systray import SysTrayIcon   # pip install infi.systray

from client_db_utils import get_or_create_hash_db

ACTION_TIMER = 90

class BackupState:
    """Track backup state to prevent overlaps and handle concurrent schedules"""
    def __init__(self):
        self.backup_in_progress = False
        self.backup_start_time = None
        self.last_successful_backup = None
        self.current_backup_source = None  # 'weekly', 'monthly', or None
        self._lock = threading.Lock()
        logging.info("Initialized new BackupState instance")

    def start_backup(self, source):
        """
        Attempt to start a new backup process.
        Returns True if backup can start, False if another backup is in progress.
        """
        with self._lock:
            if self.backup_in_progress:
                logging.warning(
                    f"Cannot start {source} backup - another backup is already in progress "
                    f"(started at {self.backup_start_time}, "
                    f"running for {self.get_backup_duration():.1f} seconds)"
                )
                return False

            self.backup_in_progress = True
            self.backup_start_time = datetime.now()
            self.current_backup_source = source
            logging.info(
                f"Starting {source} backup at {self.backup_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return True

    def complete_backup(self, success=True):
        """
        Mark the current backup as complete.
        Updates last_successful_backup if the backup was successful.
        """
        with self._lock:
            duration = self.get_backup_duration()
            if success:
                self.last_successful_backup = self.backup_start_time
                logging.info(
                    f"Successfully completed {self.current_backup_source} backup. "
                    f"Duration: {duration:.1f} seconds. "
                    f"Started at: {self.backup_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
            else:
                logging.error(
                    f"Backup failed for {self.current_backup_source}. "
                    f"Duration: {duration:.1f} seconds. "
                    f"Started at: {self.backup_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )

            self.backup_in_progress = False
            self.backup_start_time = None
            old_source = self.current_backup_source
            self.current_backup_source = None
            
            logging.debug(
                f"Reset backup state after {old_source} backup. "
                f"Last successful backup: {self.last_successful_backup.strftime('%Y-%m-%d %H:%M:%S') if self.last_successful_backup else 'None'}"
            )

    def get_backup_duration(self):
        """
        Calculate the duration of the current backup in seconds.
        Returns 0 if no backup is in progress.
        """
        if self.backup_in_progress and self.backup_start_time:
            duration = (datetime.now() - self.backup_start_time).total_seconds()
            logging.debug(
                f"Current {self.current_backup_source} backup running for {duration:.1f} seconds"
            )
            return duration
        return 0

    def get_state_summary(self):
        """
        Get a human-readable summary of the current backup state.
        Useful for debugging and monitoring.
        """
        state = {
            "backup_in_progress": self.backup_in_progress,
            "current_source": self.current_backup_source,
            "start_time": self.backup_start_time.strftime('%Y-%m-%d %H:%M:%S') if self.backup_start_time else None,
            "duration": f"{self.get_backup_duration():.1f}s" if self.backup_in_progress else "0s",
            "last_successful": self.last_successful_backup.strftime('%Y-%m-%d %H:%M:%S') if self.last_successful_backup else None
        }
        logging.debug(f"Backup state summary: {json.dumps(state, indent=2)}")
        return state

    def check_timeout(self, timeout_seconds=3600):
        """
        Check if the current backup has exceeded the timeout threshold.
        Returns True if backup has timed out, False otherwise.
        """
        if not self.backup_in_progress:
            return False

        duration = self.get_backup_duration()
        if duration > timeout_seconds:
            logging.error(
                f"Backup timeout detected for {self.current_backup_source} backup. "
                f"Duration: {duration:.1f} seconds exceeds timeout of {timeout_seconds} seconds. "
                f"Started at: {self.backup_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            return True
            
        return False

class BackupResult:
    """Represent the detailed result of a backup operation"""
    BACKED_UP = "backed_up"  # File was backed up successfully
    UNCHANGED = "unchanged"  # File was unchanged, no backup needed
    FAILED = "failed"    # Backup attempt failed
    
class InitiationSource(Enum):
    REALTIME = "Realtime"
    SCHEDULED = "Scheduled"
    USER = "User-Initiated"

class OperationStatus(Enum):
    SUCCESS = "Success"
    FAILED = "Failed"
    IN_PROGRESS = "In Progress"

@dataclass
class FileOperationRecord:
    filepath: str
    timestamp: datetime
    status: OperationStatus
    error_message: Optional[str] = None

@dataclass
class HistoryEvent:
    timestamp: datetime
    source: InitiationSource
    status: OperationStatus
    operation_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    files: List[FileOperationRecord] = field(default_factory=list)
    error_message: Optional[str] = None

class CoreHistoryManager:
    """Simplified version of HistoryManager for core engine use"""
    def __init__(self, install_path):
        self.history_dir = os.path.join(install_path, 'history')
        self.backup_history_file = os.path.join(self.history_dir, 'backup_history.json')
        self.active_operations = {}
        
        # Create directory if it doesn't exist
        os.makedirs(self.history_dir, exist_ok=True)
        
        # Initialize history file if it doesn't exist
        if not os.path.exists(self.backup_history_file):
            self.write_history(self.backup_history_file, [])

    def start_operation(self, source: InitiationSource) -> str:
        """Start a new backup operation and return its ID"""
        event = HistoryEvent(
            timestamp=datetime.now(),
            source=source,
            status=OperationStatus.IN_PROGRESS
        )
        self.active_operations[event.operation_id] = event
        self.add_event('backup', event)
        return event.operation_id

    def add_file_record(self, operation_id: str, filepath: str, 
                       status: OperationStatus, error_message: Optional[str] = None):
        """Add a file record to an operation"""
        if operation_id in self.active_operations:
            event = self.active_operations[operation_id]
            file_record = FileOperationRecord(
                filepath=filepath,
                timestamp=datetime.now(),
                status=status,
                error_message=error_message
            )
            event.files.append(file_record)
            self.add_event('backup', event)

    def complete_operation(self, operation_id: str, final_status: OperationStatus, 
                         error_message: Optional[str] = None):
        """Complete an operation with final status"""
        if operation_id in self.active_operations:
            event = self.active_operations[operation_id]
            event.status = final_status
            event.error_message = error_message
            self.add_event('backup', event)
            del self.active_operations[operation_id]

    def read_history(self, file_path: str) -> list:
        """Read history from JSON file"""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def write_history(self, file_path: str, history: list):
        """Write history to JSON file"""
        with open(file_path, 'w') as f:
            json.dump(history, f, indent=2)

    def event_to_dict(self, event: HistoryEvent) -> dict:
        """Convert HistoryEvent to dictionary for storage"""
        return {
            'timestamp': event.timestamp.isoformat(),
            'source': event.source.value,
            'status': event.status.value,
            'operation_id': event.operation_id,
            'error_message': event.error_message,
            'files': [
                {
                    'filepath': f.filepath,
                    'timestamp': f.timestamp.isoformat(),
                    'status': f.status.value,
                    'error_message': f.error_message
                }
                for f in event.files
            ]
        }

    def add_event(self, event_type: str, event: HistoryEvent):
        """Add or update an event in history"""
        history = self.read_history(self.backup_history_file)
        
        # Convert event to dictionary
        event_dict = self.event_to_dict(event)
        
        # Find and update existing entry if it exists
        updated = False
        for i, existing_event in enumerate(history):
            if existing_event.get('operation_id') == event.operation_id:
                history[i] = event_dict
                updated = True
                break
                
        # Add as new entry if it doesn't exist
        if not updated:
            history.append(event_dict)
        
        # Write back to file
        self.write_history(self.backup_history_file, history)

def should_backup(schedule, last_check_time, backup_state):
    """
    Enhanced backup check handling concurrent schedules and system time changes
    """
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    last_check_str = last_check_time.strftime("%H:%M")
    day_changed = now.date() != last_check_time.date()
    
    # Detect significant time changes (more than 5 minutes)
    time_jump = abs((now - last_check_time).total_seconds()) > 300
    if time_jump:
        logging.warning(f"Detected significant time change: {last_check_time} -> {now}")
    
    # Check if backup is currently running
    if backup_state.backup_in_progress:
        duration = backup_state.get_backup_duration()
        if duration > 3600:  # 1 hour timeout
            logging.error(f"Backup has been running for {duration} seconds. Force marking as complete.")
            backup_state.complete_backup(success=False)
        else:
            return False, None

    # Initialize variables for concurrent schedule handling
    should_run = False
    trigger_source = None

    # Check weekly schedule
    weekday = calendar.day_name[now.weekday()]
    if weekday in schedule.get('weekly', {}):
        if current_time in schedule['weekly'][weekday]:
            if last_check_str <= current_time or day_changed or time_jump:
                should_run = True
                trigger_source = 'weekly'

    # Check monthly schedule
    day_of_month = str(now.day)
    
    # Handle Last day of month
    if "Last day" in schedule.get('monthly', {}):
        last_day = calendar.monthrange(now.year, now.month)[1]
        if now.day == last_day:
            if current_time in schedule['monthly']["Last day"]:
                if last_check_str <= current_time or day_changed or time_jump:
                    should_run = True
                    trigger_source = 'monthly'

    # Handle regular monthly days (1-28)
    if day_of_month in schedule.get('monthly', {}):
        if current_time in schedule['monthly'][day_of_month]:
            if last_check_str <= current_time or day_changed or time_jump:
                should_run = True
                trigger_source = 'monthly'

    return should_run, trigger_source

def main(settings_file_path,hash_db_file_path,ignore_hash_db):
    # Honor SSLKEYLOGFILE if set by the OS
    # sslkeylog.set_keylog(os.environ.get('SSLKEYLOGFILE'))

    if settings_file_path == 'use_app_data':
        settings_file_path = _get_settings_path_from_install()

        if not settings_file_path:
            logging.log(logging.ERROR, "Unable to find settings file. Exiting!")
            exit()

    settings = read_yaml_settings_file(settings_file_path)

    if int(settings['SEND_LOGS']):
        logging_utils.send_logs_to_server(settings['API_KEY'],settings['AGENT_ID'])
    
    logging_utils.initialize_logging(uuid=settings['AGENT_ID'])

    hash_db_conn = get_or_create_hash_db(hash_db_file_path)

    systray_menu_options = (
        (
            "Backup now",
            None,
            lambda x: logging.log(logging.INFO, "User clicked 'Backup now', but backup is always running.")
        )
    ,)
    systray = SysTrayIcon("stormcloud.ico", "Stormcloud Backup Engine", systray_menu_options)
    systray.start()

    action_loop_and_sleep(settings=settings,settings_file_path=settings_file_path,dbconn=hash_db_conn,ignore_hash=ignore_hash_db,systray=systray)

def save_file_metadata(settings):
    """Save file metadata to the manifest directory"""
    api_key = settings['API_KEY']
    agent_id = settings['AGENT_ID']
    
    metadata = network_utils.fetch_file_metadata(api_key, agent_id)
    
    if metadata:
        # Get installation path from settings
        appdata_path = os.getenv('APPDATA')
        settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
        
        try:
            with open(settings_path, 'r') as f:
                stable_settings = json.load(f)
            install_path = stable_settings.get('install_path', '')
            
            # Create manifest directory
            manifest_dir = os.path.join(install_path, 'file_explorer', 'manifest')
            os.makedirs(manifest_dir, exist_ok=True)
            
            # Save new metadata file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"file_metadata_{timestamp}.json"
            file_path = os.path.join(manifest_dir, filename)
            
            with open(file_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logging.info(f"File metadata saved to {file_path}")
            
            # Cleanup old files
            cleanup_old_metadata(manifest_dir)
            
        except Exception as e:
            logging.error(f"Failed to save metadata: {e}")
    else:
        logging.error("Failed to fetch file metadata")

def cleanup_old_metadata(manifest_dir, max_files=10):
    """Remove old metadata files keeping only the most recent ones"""
    try:
        # Get list of metadata files
        files = [f for f in os.listdir(manifest_dir) 
                if f.startswith('file_metadata_') and f.endswith('.json')]
        
        # Sort by timestamp in filename
        files.sort(key=lambda x: datetime.strptime(
            x, 'file_metadata_%Y%m%d_%H%M%S.json'), reverse=True)
        
        # Remove old files
        if len(files) > max_files:
            for old_file in files[max_files:]:
                file_path = os.path.join(manifest_dir, old_file)
                try:
                    os.remove(file_path)
                    logging.info(f"Removed old metadata file: {old_file}")
                except Exception as e:
                    logging.error(f"Failed to remove old metadata file {old_file}: {e}")
                    
    except Exception as e:
        logging.error(f"Error during metadata cleanup: {e}")

def action_loop_and_sleep(settings, settings_file_path, dbconn, ignore_hash, systray):
    active_thread = None
    last_check_time = datetime.now()
    backup_state = BackupState()
    
    # Initialize history manager
    appdata_path = os.getenv('APPDATA')
    settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')
    with open(settings_path, 'r') as f:
        stable_settings = json.load(f)
    install_path = stable_settings.get('install_path', '')
    history_manager = CoreHistoryManager(install_path)

    while True:
        try:
            settings = read_yaml_settings_file(settings_file_path)
            network_utils.sync_backup_folders(settings)

            # Handle keepalive thread
            cur_keepalive_freq = int(settings['KEEPALIVE_FREQ'])
            if active_thread is None or not active_thread.is_alive():
                active_thread = start_keepalive_thread(
                    cur_keepalive_freq,
                    settings['API_KEY'],
                    settings['AGENT_ID']
                )

            backup_mode = settings.get('BACKUP_MODE', 'Realtime')
            current_time = datetime.now()

            if backup_mode == 'Realtime':
                if not backup_state.backup_in_progress:
                    # Start backup operation in history
                    operation_id = history_manager.start_operation(InitiationSource.REALTIME)
                    backup_state.start_backup('realtime')
                    
                    try:
                        success = perform_backup_with_history(
                            settings['BACKUP_PATHS'],
                            settings['RECURSIVE_BACKUP_PATHS'],
                            settings,
                            dbconn,
                            ignore_hash,
                            systray,
                            history_manager,
                            operation_id
                        )
                        save_file_metadata(settings)
                        backup_state.complete_backup(success=success)
                        
                        final_status = OperationStatus.SUCCESS if success else OperationStatus.FAILED
                        history_manager.complete_operation(operation_id, final_status)
                        
                    except Exception as e:
                        logging.error(f"Backup failed: {str(e)}")
                        backup_state.complete_backup(success=False)
                        history_manager.complete_operation(
                            operation_id,
                            OperationStatus.FAILED,
                            str(e)
                        )
                    
                last_check_time = current_time
                sleep(ACTION_TIMER)
                
            else:  # Scheduled mode
                schedule = parse_schedule(settings)
                should_run, source = should_backup(schedule, last_check_time, backup_state)
                
                if should_run and source:
                    if backup_state.start_backup(source):
                        # Start backup operation in history
                        operation_id = history_manager.start_operation(InitiationSource.SCHEDULED)
                        
                        try:
                            success = perform_backup_with_history(
                                settings['BACKUP_PATHS'],
                                settings['RECURSIVE_BACKUP_PATHS'],
                                settings,
                                dbconn,
                                ignore_hash,
                                systray,
                                history_manager,
                                operation_id
                            )
                            save_file_metadata(settings)
                            backup_state.complete_backup(success=success)
                            
                            final_status = OperationStatus.SUCCESS if success else OperationStatus.FAILED
                            history_manager.complete_operation(operation_id, final_status)
                            
                        except Exception as e:
                            logging.error(f"Scheduled backup failed: {str(e)}")
                            backup_state.complete_backup(success=False)
                            history_manager.complete_operation(
                                operation_id,
                                OperationStatus.FAILED,
                                str(e)
                            )
                
                last_check_time = current_time
                sleep(ACTION_TIMER)
            
        except Exception as e:
            logging.error(f"Error in backup loop: {str(e)}")
            sleep(ACTION_TIMER)

def perform_backup_with_history(backup_paths, recursive_paths, settings, dbconn, 
                              ignore_hash, systray, history_manager, operation_id):
    """Perform backup with history tracking"""
    success = True
    files_processed = False  # Track if we actually processed any files
    
    def normalize_path(path):
        """Normalize path to use forward slashes"""
        return str(path).replace('\\', '/')
    
    def process_path(path, is_recursive=False):
        nonlocal success, files_processed
        path = normalize_path(path)
        
        try:
            if os.path.isfile(path):
                try:
                    backup_result = backup_utils.process_file(
                        pathlib.Path(path),
                        settings['API_KEY'],
                        settings['AGENT_ID'],
                        dbconn,
                        ignore_hash
                    )
                    
                    if backup_result == BackupResult.BACKED_UP:
                        files_processed = True
                        history_manager.add_file_record(
                            operation_id,
                            path,
                            OperationStatus.SUCCESS,
                            None
                        )
                    elif backup_result == BackupResult.FAILED:
                        files_processed = True
                        success = False
                        history_manager.add_file_record(
                            operation_id,
                            path,
                            OperationStatus.FAILED,
                            "Backup operation failed"
                        )
                    # Skip recording UNCHANGED files
                    
                except Exception as e:
                    files_processed = True
                    success = False
                    error_msg = str(e)
                    logging.error(f"Error backing up file {path}: {error_msg}")
                    history_manager.add_file_record(
                        operation_id,
                        path,
                        OperationStatus.FAILED,
                        error_msg
                    )
                    
            elif is_recursive:  # Directory with recursive backup
                for root, _, files in os.walk(path):
                    for file in files:
                        file_path = normalize_path(os.path.join(root, file))
                        try:
                            file_success = backup_utils.process_file(
                                pathlib.Path(file_path),
                                settings['API_KEY'],
                                settings['AGENT_ID'],
                                dbconn,
                                ignore_hash
                            )
                            status = OperationStatus.SUCCESS if file_success else OperationStatus.FAILED
                            history_manager.add_file_record(
                                operation_id, 
                                file_path, 
                                status,
                                None if file_success else "File backup failed"
                            )
                            if not file_success:
                                success = False
                                logging.error(f"Failed to backup file: {file_path}")
                        except Exception as e:
                            success = False
                            error_msg = str(e)
                            logging.error(f"Error backing up file {file_path}: {error_msg}")
                            history_manager.add_file_record(
                                operation_id,
                                file_path,
                                OperationStatus.FAILED,
                                error_msg
                            )
            
            elif os.path.isdir(path):  # Directory without recursive backup
                # Only process files in the immediate directory
                for entry in os.scandir(path):
                    if entry.is_file():
                        file_path = normalize_path(entry.path)
                        try:
                            file_success = backup_utils.process_file(
                                pathlib.Path(file_path),
                                settings['API_KEY'],
                                settings['AGENT_ID'],
                                dbconn,
                                ignore_hash
                            )
                            status = OperationStatus.SUCCESS if file_success else OperationStatus.FAILED
                            history_manager.add_file_record(
                                operation_id, 
                                file_path, 
                                status,
                                None if file_success else "File backup failed"
                            )
                            if not file_success:
                                success = False
                                logging.error(f"Failed to backup file: {file_path}")
                        except Exception as e:
                            success = False
                            error_msg = str(e)
                            logging.error(f"Error backing up file {file_path}: {error_msg}")
                            history_manager.add_file_record(
                                operation_id,
                                file_path,
                                OperationStatus.FAILED,
                                error_msg
                            )

        except Exception as e:
            files_processed = True
            success = False
            error_msg = f"Error processing path {path}: {str(e)}"
            logging.error(error_msg)
            history_manager.add_file_record(
                operation_id,
                path,
                OperationStatus.FAILED,
                error_msg
            )

    # Process backup paths
    logging.info("Processing regular backup paths: %s", backup_paths)
    for path in backup_paths:
        process_path(path, False)

    # Process recursive backup paths
    logging.info("Processing recursive backup paths: %s", recursive_paths)
    for path in recursive_paths:
        process_path(path, True)

    # If no files needed processing, consider it a success
    if not files_processed:
        success = True

    return success

def parse_schedule(settings):
    """Parse the BACKUP_SCHEDULE from settings and return structured schedule data"""
    schedule_str = settings.get('BACKUP_SCHEDULE', '{}')
    if isinstance(schedule_str, str):
        try:
            schedule = json.loads(schedule_str)
        except json.JSONDecodeError:
            logging.error("Failed to parse BACKUP_SCHEDULE JSON")
            return {'weekly': {}, 'monthly': {}}
    else:
        schedule = schedule_str
    return schedule

def read_yaml_settings_file(fn):
    with open(fn, 'r') as settings_file:
        return yaml.safe_load(settings_file)

def _get_settings_path_from_install():
    """
        Parses stable_settings.cfg to get install directory.
        Returns path: <install directory> + 'settings.cfg'.
    """
    success = False

    # Get installation path from settings
    appdata_path = os.getenv('APPDATA')
    stable_settings_path = os.path.join(appdata_path, 'Stormcloud', 'stable_settings.cfg')

    try:
        with open(stable_settings_path, 'r') as f:
            stable_settings = json.load(f)
        install_path = stable_settings.get('install_path', '')
            
        # By default, should be named settings.cfg in install directory.
        settings_file_path = os.path.join(install_path, 'settings.cfg')
        success = True

    except Exception as e:
        print(traceback.format_exc())
        pass
    finally:
        if success:
            return settings_file_path
        else:
            return None

def start_keepalive_thread(freq,api_key,agent_id):
    logging.log(logging.INFO,"starting new keepalive thread with freq %d" % freq)

    t = threading.Thread(target=keepalive_utils.execute_ping_loop,args=(freq,api_key,agent_id))
    t.start()

    logging.log(logging.INFO,"returning from start thread")
    return t

if __name__ == "__main__":
    description = r"""

        ______     ______   ______     ______     __    __                    
       /\  ___\   /\__  _\ /\  __ \   /\  == \   /\ "-./  \                   
       \ \___  \  \/_/\ \/ \ \ \/\ \  \ \  __<   \ \ \-./\ \                  
        \/\_____\    \ \_\  \ \_____\  \ \_\ \_\  \ \_\ \ \_\                 
         \/_____/     \/_/   \/_____/   \/_/ /_/   \/_/  \/_/                 
                                                                              
                    ______     __         ______     __  __     _____         
                   /\  ___\   /\ \       /\  __ \   /\ \/\ \   /\  __-.       
                   \ \ \____  \ \ \____  \ \ \/\ \  \ \ \_\ \  \ \ \/\ \      
                    \ \_____\  \ \_____\  \ \_____\  \ \_____\  \ \____-      
                     \/_____/   \/_____/   \/_____/   \/_____/   \/____/      
                                                                              
                                   ______     ______     ______     ______    
                                  /\  ___\   /\  __ \   /\  == \   /\  ___\   
                                  \ \ \____  \ \ \/\ \  \ \  __<   \ \  __\   
                                   \ \_____\  \ \_____\  \ \_\ \_\  \ \_____\ 
                                    \/_____/   \/_____/   \/_/ /_/   \/_____/ 
                                                                                                                                                                                                                                                                           

    """

    description += 'Welcome to Stormcloud, the best backup system!'
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-s", "--settings-file",type=str,default="use_app_data",help="Path to settings file (default=<install directory>/settings.cfg)")
    parser.add_argument("-d", "--hash-db", type=str, default="schash.db", help="Path to hash db file (default=./schash.db")
    parser.add_argument("-o", "--ignore-hash-db", action="store_true", help="override the hash db, to backup files even if they haven't changed")

    args = parser.parse_args()
    main(args.settings_file,args.hash_db,args.ignore_hash_db)