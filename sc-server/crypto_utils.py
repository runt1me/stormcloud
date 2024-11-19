import os

import secrets
import string
import random
from cryptography.fernet import Fernet

import logging_utils
import database_utils as db

def __logger__():
    return logging_utils.logger

def generate_api_key():
    api_key = ""
    valid_token = False

    while not valid_token:
      api_key = secrets.token_urlsafe(16)

      if db.passes_sanitize(api_key):
        valid_token = True

      # Replace "-" with "_" to better accommodate some frontend display-logic
      api_key = api_key.replace("-", "_")

    return api_key

def generate_agent_id():
    valid_token = False
    token = ""

    while not valid_token:
      token = secrets.token_urlsafe(8) + "_" + secrets.token_urlsafe(8)

      if db.passes_sanitize(token):
        valid_token = True

      # Replace "-" with "_" to better accommodate some frontend display-logic
      token = token.replace("-", "_")

    return token

def generate_customer_guid():
    valid_token = False
    token = ""

    characters = string.ascii_letters + string.digits

    while not valid_token:
      token = ''.join(random.choice(characters) for _ in range(32))

      if db.passes_sanitize(token):
        valid_token = True

    return token
