from time import sleep
from datetime import datetime, timedelta

#number of seconds in between actions
ACTION_TIMER = 90

def main():
    if not hash_db_exists():
        print("no database found, creating")
        create_hash_db()

    else:
        print("getting hash db")
        hash_db = get_hash_db()

    action_loop_and_sleep()

def hash_db_exists():
    pass

def create_hash_db():
    pass

def get_hash_db():
    pass

def action_loop_and_sleep():
    PREV_RUN_TIME = datetime.now() - timedelta(minutes=2)

    #daemon loop
    #eventually change to while true
    while True:
        sleep(ACTION_TIMER)
        settings = read_settings_file()
        CURRENT_RUN_TIME = datetime.now()
        print("running at time %s with settings: %s" % (CURRENT_RUN_TIME,settings))

        if check_for_backup(settings,CURRENT_RUN_TIME,PREV_RUN_TIME):
            print("Time for the backup!")
            perform_backup()
        else:
            print("Going back to sleep...")

        PREV_RUN_TIME = CURRENT_RUN_TIME

def read_settings_file(fn="settings.cfg"):
    #TODO:
    #fail gracefully if settings are not complete?
    #revert to last known good settings?
    with open(fn,'r') as settings_file:
        settings_lines = [l for l in settings_file.read().split('\n') if l]
        settings_lines = [l for l in settings_lines if l[0] != "#"]

        settings = {}
        for s in settings_lines:
            settings[s.split()[0]] = s.split()[1]

    return settings

def check_for_backup(settings_dict,current_run_time,previous_run_time):
    datetime_of_backup = datetime(
        year=datetime.now().year,
        month=datetime.now().month,
        day=datetime.now().day,
        hour=int(settings_dict['BACKUP_TIME']),
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

def perform_backup():
    print("Backing up!")
    exit()

if __name__ == "__main__":
    main()