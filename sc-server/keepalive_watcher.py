from time import sleep

WATCH_INTERVAL = 90

def main():
    while True:
        with open("/root/stormcloud/keepalives.csv","r") as keepalive_file:
            all_clients_and_keepalives = [
                (l.split(",")[0],l.split(",")[1]) 
                for l in keepalive_file.read().split('\n') if l
            ]
            
            print(all_clients_and_keepalives)

        print("sleeping...")
        sleep(WATCH_INTERVAL)







if __name__ == "__main__":
    main()