# covers

Maps covers from home assistant to relays on unipi.

## Quickstart

### Installation

With [poetry]; install a local virtualenv

    poetry install

[poetry]: https://poetry.eustace.io/

### Building

Export the requirements from poetry

    poetry export --without-hashes -o requirements.txt

### Commands

Help:

```
    usage: covers.py [-h][--mqtt_host mqtt_host] [--mqtt_base_topic_cover MQTT_BASE_TOPIC_COVER][--mqtt_base_topic_relay mqtt_base_topic_relay] config

    positional arguments:
    config Config file mapping covers to relays

    optional arguments:
    -h, --help show this help message and exit
    --mqtt_host MQTT_HOST MQTT broker host
    --mqtt_base_topic_cover MQTT_BASE_TOPIC_COVER
    --mqtt_base_topic_relay MQTT_BASE_TOPIC_RELAY
```

### Example config file

The config file is supposed to be in this format:

```yaml
    office_side:
      open: "3_14"
      close:"3_13"
    office_front:
      open: "3_11"
      close: "3_12"
```

## homeassistant integration

This application is developed to play along nicely with [home assistant MQTT cover](https://www.home-assistant.io/integrations/cover.mqtt/).

A simple setup to get you going:

docker-compose:

```yaml
version: "3"
services:
  homeassistant:
    image: homeassistant/home-assistant
    restart: unless-stopped
    ports:
      - "8123:8123"
    volumes:
      - .:/config
      - /etc/localtime:/etc/localtime:ro
    environment:
      MQTT_BROKER: 192.168.1.2
```

Related config file:

```yaml
default_config:

mqtt:
  broker: !env_var MQTT_BROKER

# Cover config
cover:
  - platform: mqtt
    name: "office"
    command_topic: "homeassistant/cover/office/set"
    state_topic: "homeassistant/cover/office/state"
    position_topic: "homeassistant/cover/office/position"
    set_position_topic: "covers/office/set_position"
    device_class: shade
    optimistic: true

# Toggle buttons
switch:
  - platform: mqtt
    name: office open
    command_topic: "shady/input/3_09/set"
    state_topic: "shady/input/3_09/state"

  - platform: mqtt
    name: office close
    command_topic: "shady/input/3_10/set"
    state_topic: "shady/input/3_10/state"

# Link toggle buttons to cover actions
automation:
  - alias: Office toggle open start
    trigger:
      platform: state
      entity_id: switch.office_open
      from: "off"
      to: "on"
    action:
      service: cover.open_cover
      entity_id: cover.office

  - alias: Office toggle open stop
    trigger:
      platform: state
      entity_id: switch.office_open
      from: "on"
      to: "off"
    action:
      service: cover.stop_cover
      entity_id: cover.office

  - alias: Office toggle close start
    trigger:
      platform: state
      entity_id: switch.office_close
      from: "off"
      to: "on"
    action:
      service: cover.close_cover
      entity_id: cover.office

  - alias: Office toggle close stop
    trigger:
      platform: state
      entity_id: switch.office_close
      from: "on"
      to: "off"
    action:
      service: cover.stop_cover
      entity_id: cover.office
```

Notes:

- Using cover in "optimistic" mode, since home assistant isn't clever enough to be able switch between opening and closing.
