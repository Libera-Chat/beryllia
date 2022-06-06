from dataclasses import dataclass
from os.path import expanduser
from typing import Optional, Sequence, Tuple

import yaml


@dataclass
class Config(object):
    server: str
    nickname: str
    username: str
    realname: str
    password: Optional[str]
    channels: Sequence[str]
    log: Optional[str]
    rejects: int

    sasl: Tuple[str, str]
    oper: Tuple[str, str, str]

    db_user: str
    db_pass: Optional[str]
    db_host: Optional[str]
    db_name: str


def load(filepath: str):
    with open(filepath) as file:
        config_yaml = yaml.safe_load(file.read())

    nickname = config_yaml["nickname"]

    oper_name = config_yaml["oper"]["name"]
    oper_file = expanduser(config_yaml["oper"]["file"])
    oper_pass = config_yaml["oper"]["pass"]

    return Config(
        config_yaml["server"],
        nickname,
        config_yaml.get("username", nickname),
        config_yaml.get("realname", nickname),
        config_yaml.get("password", None),
        config_yaml["channels"],
        config_yaml.get("log", None),
        config_yaml["rejects"],
        (config_yaml["sasl"]["username"], config_yaml["sasl"]["password"]),
        (oper_name, oper_file, oper_pass),
        config_yaml["database"]["user"],
        config_yaml["database"].get("pass", None),
        config_yaml["database"].get("host", None),
        config_yaml["database"]["name"],
    )
