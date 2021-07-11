from time import sleep
from datetime import datetime, timedelta

WATCH_INTERVAL = 90
ONE_DAY = timedelta(days=1)

def main():
    while True:
        with open("/root/stormcloud/keepalives.csv","r") as keepalive_file:
            all_clients_and_keepalives = [
                (int(l.split(",")[0]),l.split(",")[1]) 
                for l in keepalive_file.read().split('\n') if l
            ]

        print(all_clients_and_keepalives)
            
        for client,last_ping_time in all_clients_and_keepalives:
            last_ping_datetime = datetime.strptime(last_ping_time,"%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_ping_datetime > ONE_DAY:
                print("client %d has not pinged back within the last day" % client)


        print("sleeping...")
        sleep(WATCH_INTERVAL)


if __name__ == "__main__":
    main()
