import logging

def initialize_logging():
    logging.basicConfig(
            filename='/var/log/stormcloud_installer.log',
            filemode='a',
            format='%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG
    )

