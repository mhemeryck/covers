import yaml

with open("switches.yaml") as fh:
    config = yaml.safe_load(fh)

switches = []
automations = []
for name, relay_map in config.items():
    cleaned_name = name.replace("_", " ")
    # Switch open
    i = relay_map["open"]["input"]
    switches.append(
        {
            "platform": "mqtt",
            "name": f"{cleaned_name} open",
            "command_topic": f"shady/input/{i}/command",
            "state_topic": f"shady/input/{i}/state",
        }
    )
    # Switch close
    i = relay_map["close"]["input"]
    switches.append(
        {
            "platform": "mqtt",
            "name": f"{cleaned_name} close",
            "command_topic": f"shady/input/{i}/command",
            "state_topic": f"shady/input/{i}/state",
        }
    )
    # Automation toggle open start
    automations.append(
        {
            "alias": f"toggle cover {cleaned_name} open start",
            "trigger": {
                "platform": "state",
                "entity_id": f"switch.{name}_open",
                "from": "off",
                "to": "on",
            },
            "action": {
                "service": "cover.open_cover",
                "entity_id": f"cover.{name}",
            },
        }
    )
    # Automation toggle open stop
    automations.append(
        {
            "alias": f"toggle cover {cleaned_name} open stop",
            "trigger": {
                "platform": "state",
                "entity_id": f"switch.{name}_open",
                "from": "on",
                "to": "off",
            },
            "action": {
                "service": "cover.stop_cover",
                "entity_id": f"cover.{name}",
            },
        }
    )
    # Automation toggle close start
    automations.append(
        {
            "alias": f"toggle cover {cleaned_name} open start",
            "trigger": {
                "platform": "state",
                "entity_id": f"switch.{name}_close",
                "from": "off",
                "to": "on",
            },
            "action": {
                "service": "cover.close_cover",
                "entity_id": f"cover.{name}",
            },
        }
    )
    # Automation toggle open stop
    automations.append(
        {
            "alias": f"toggle cover {cleaned_name} close stop",
            "trigger": {
                "platform": "state",
                "entity_id": f"switch.{name}_close",
                "from": "on",
                "to": "off",
            },
            "action": {
                "service": "cover.stop_cover",
                "entity_id": f"cover.{name}",
            },
        }
    )

outfile = "generated.yaml"
with open("generated.yaml", "w") as fh:
    yaml.safe_dump(
        {"switch": switches, "automation": automations}, stream=fh, sort_keys=False
    )
