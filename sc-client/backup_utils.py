from datetime import datetime, timedelta
from os import walk
import pathlib

def check_for_backup(backup_time,current_run_time,previous_run_time):
    datetime_of_backup = datetime(
        year=datetime.now().year,
        month=datetime.now().month,
        day=datetime.now().day,
        hour=backup_time,
        minute=0,
        second=0
    )

    print("PREVIOUS RUN: %s" % previous_run_time)
    print("BACKUP TIME: %s" % datetime_of_backup)
    print("CURRENT RUN: %s" % current_run_time)

    if previous_run_time < datetime_of_backup and current_run_time > datetime_of_backup:
        return True
    else:
        return False

def perform_backup(paths):
    print("\n\n\nBacking up!\n\n\n")
    for path in paths.split(","):
        print("==   %s   ==" % path)
        path_obj = pathlib.Path(path)

        if path_obj.is_file():
            print("%s is a file" % path)
            process_file(path_obj)

        elif path_obj.is_dir():
            print("%s is a dir" % path)
            for file_obj in [p for p in path_obj.iterdir() if p.is_file()]:
                process_file(file_obj)

        dirns = []
        for (dirpath, dirnames, filenames) in walk(path):
            dirns.extend(dirnames)
            break

        for dirn in dirns:
            print("dir: %s" % dirn)


def process_file(file_path_obj):
    file_name = file_path_obj.name
    file_content = file_path_obj.read_bytes()
    file_size = file_path_obj.stat().st_size
    
    ship_file_to_server(file_name,file_content,file_size)

def ship_file_to_server(name,content,size):
    print("mailing file")