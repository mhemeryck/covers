# covers

Maps covers from home assistant to relays on unipi.

## Example config file

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
