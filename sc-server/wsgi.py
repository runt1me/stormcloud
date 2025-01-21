import sys
sys.path.insert(0,"/var/www/api/")

import os
import dotenv

# Load environment variables
env_path = '/etc/stormcloud/.env'
if os.path.exists(env_path):
    dotenv.load_dotenv(env_path)

from server_main import app as application
