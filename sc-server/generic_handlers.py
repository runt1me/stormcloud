import json

import database_utils as db
import logging_utils

def __logger__():
    return logging_utils.logger

def handle_hello_request(request):
    __logger__().info("Server handling hello request.")
    response_data = json.dumps({
        'hello-response': 'Goodbye'
    })

    return 200, response_data

def handle_validate_api_key_request(request):
    __logger__().info("Server handling validate API key request.")
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 401,json.dumps({'response': 'Invalid API key.'})

    return 200, json.dumps({'validate_api_key-response': 'Valid API key.'})

def handle_get_builds_request(request):
    __logger__().info("Server handling get builds request.")

    builds_from_db = db.get_pending_builds()
    builds = []

    if not builds_from_db:
      return 200, json.dumps({'get_builds-response': 'No pending builds.'})

    __logger__().info("Got list of pending builds: %s" % builds_from_db)

    for b in builds_from_db:
      build_id = b[0]

      build_dict = {}
      build_dict['target']      = b[1]
      build_dict['version']     = b[2]
      build_dict['environment'] = b[3]
      build_dict['signing_pin'] = b[4]

      builds.append(build_dict)

      # TODO: currently just marking it as complete here,
      # in theory I could have the build service fire off
      # an API request to hit this when it is done
      db.mark_build_complete(build_id)

    response_data = json.dumps({
      'get_builds-response': 'Heres a build or two for ya',
      'build-list': builds
    })

    return 200, response_data

def handle_build_software_request(request):
    __logger__().info("Server handling build software request.")
    customer_id = db.get_customer_id_by_api_key(request['api_key'])

    if not customer_id:
        return 401,json.dumps({'response': 'Invalid API key.'})

    # Method-specific parameter validation
    success = False
    params_valid = True
    try:
        pin      = int(request['pin'])
        env      = str(request['environment']).lower()
        software = str(request['software']).lower()

        if env not in ['dev', 'prod', 'all']:
            raise Exception("Invalid environment parameter.")

        if software not in ['client', 'manager', 'installer', 'uninstaller']:
            raise Exception("Invalid software parameter.")

    except Exception as e:
        params_valid = False
        return 400,json.dumps({'response': e})

    if params_valid:
      success = db.add_new_build_request(
          request['version'],
          env,
          software,
          pin
      )

      __logger__().info("Database returned: %d" % success)

    if success:
        return 200, json.dumps({'build_software-response': 'Processed build request.'})

    else:
        __logger__().warning("Did not succeed when trying to submit build request.")
        return 400,json.dumps({'response': 'Something went wrong.'})

