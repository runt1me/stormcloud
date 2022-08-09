import json

def recv_json_until_eol(socket):
    # Borrowed from https://github.com/mdebbar/jsonsocket

    # read the length of the data, letter by letter until we reach EOL
    length_bytes = bytearray()
    char = socket.recv(1)
    while char != bytes('\n',encoding="UTF-8"):
      length_bytes += char

      char = socket.recv(1)
    total = int(length_bytes)

    # use a memoryview to receive the data chunk by chunk efficiently
    view = memoryview(bytearray(total))
    next_offset = 0
    while total - next_offset > 0:
      recv_size = socket.recv_into(view[next_offset:], total - next_offset)
      next_offset += recv_size

    try:
      deserialized = json.loads(view.tobytes())
    except (TypeError, ValueError) as e:
      # TODO: Send error code back to client
      raise Exception('Data received was not in JSON format')

    return deserialized
