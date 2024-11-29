import sqlite3
import os

from datetime import datetime
from enum import Enum
from typing import Optional, List
from dataclasses import dataclass
from pathlib import Path

class InitiationSource(Enum):
    REALTIME = "Realtime"
    SCHEDULED = "Scheduled"
    USER = "User-Initiated"

class OperationStatus(Enum):
    SUCCESS = "Success"
    FAILED = "Failed" 
    IN_PROGRESS = "In Progress"

@dataclass
class FileRecord:
    filepath: str
    timestamp: datetime
    status: OperationStatus
    error_message: Optional[str] = None
    operation_id: Optional[str] = None

@dataclass
class Operation:
    operation_id: str
    timestamp: datetime
    source: InitiationSource
    status: OperationStatus
    error_message: Optional[str] = None
    user_email: Optional[str] = None
    operation_type: Optional[str] = None  # Make operation_type optional with default None
    files: List[FileRecord] = None

def init_db(db_path):
    # Ensure the directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            operation_id TEXT PRIMARY KEY,
            timestamp DATETIME NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            error_message TEXT
        )""")
        
        conn.execute("""
        CREATE TABLE IF NOT EXISTS file_records (
            id INTEGER PRIMARY KEY,
            operation_id TEXT NOT NULL,
            filepath TEXT NOT NULL,
            timestamp DATETIME NOT NULL, 
            status TEXT NOT NULL,
            error_message TEXT,
            FOREIGN KEY (operation_id) REFERENCES operations(operation_id)
        )""")