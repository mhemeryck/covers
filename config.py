import typing

import pydantic
import yaml

# from maus import Name


# class NameConfig(Name, pydantic.BaseModel):
#     ...


class EntryConfig(pydantic.BaseModel):
    name: str
    io: str


class CoverConfig(pydantic.BaseModel):
    name: str
    motor_up: str
    motor_down: str


class EntityConfig(pydantic.BaseModel):
    push_buttons: typing.List[EntryConfig]
    lights: typing.List[EntryConfig]
    covers: typing.List[CoverConfig]


class LightAutomation(pydantic.BaseModel):
    name: str
    push_button: str
    light: str


class CoverAutomation(pydantic.BaseModel):
    name: str
    push_button_up: str
    push_button_down: str
    cover: str


class AutomationConfig(pydantic.BaseModel):
    lights: typing.List[LightAutomation]
    covers: typing.List[CoverAutomation]


class Config(pydantic.BaseModel):
    entities: EntityConfig
    automations: AutomationConfig

    @classmethod
    def from_filename(cls, filename: str) -> typing.Self:
        with open(filename, "rb") as fh:
            data = yaml.safe_load(fh)
            return cls(**data)


def is_config_valid(config: Config) -> bool:
    """Simple check to see whether names have been used consistently"""

    push_buttons = [p.name for p in config.entities.push_buttons]
    lights = [light.name for light in config.entities.lights]
    covers = [c.name for c in config.entities.covers]

    # check light automations
    for a in config.automations.lights:
        if a.push_button not in push_buttons:
            return False
        if a.light not in lights:
            return False

    # Check cover automations
    for a in config.automations.covers:
        if a.push_button_up not in push_buttons:
            return False
        if a.push_button_down not in push_buttons:
            return False
        if a.cover not in covers:
            return False

    return True


filename = "./config2.yaml"
config = Config.from_filename(filename)
assert is_config_valid(config)
