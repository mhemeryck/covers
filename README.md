# covers

Maps covers from home assistant to relays on unipi.

## Quickstart

### Installation

With [poetry]; install a local virtualenv

    poetry install

### Commands

Help:

    poetry run python covers.py --help
    usage: covers.py [-h] [--mqtt_port MQTT_PORT] [--mqtt_client_id MQTT_CLIENT_ID] [--on_time ON_TIME] mqtt_host config inputs_base_topic relays_base_topic

    positional arguments:
      mqtt_host             MQTT broker host
      config                YAML config file
      inputs_base_topic     Base topic of device connecting to
      relays_base_topic     Relay base topic

    optional arguments:
      -h, --help            show this help message and exit
      --mqtt_port MQTT_PORT
      --mqtt_client_id MQTT_CLIENT_ID
                            Client ID to use for MQTT
      --on_time ON_TIME     Time in seconds the cover relays can on

[poetry]: https://poetry.eustace.io/

### Example config file

The config file is supposed to be in this format:

    office_side:
      open:
        input: "3_11"
        relay: "3_14"
      close:
        input: "3_12"
        relay: "3_13"
    office_front:
      open:
        input: "3_09"
        relay: "3_11"
      close:
        input: "3_10"
        relay: "3_12"
