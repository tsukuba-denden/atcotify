# env/config.py

import configparser
import os


class Config:
    def __init__(self):
        path = os.path.join(os.path.dirname(__file__), "config.ini")
        self.config = configparser.ConfigParser()
        self.config.read(path, "UTF-8")

    @property
    def token(self) -> str:
        return str(self.config["TOKEN"]["TOKEN"])

    @property
    def season(self) -> str:
        return str(self.config["SEASON"]["SEASON"])

    @property
    def atcoder_username(self) -> str:
        return str(self.config["ATCODER"]["ATCODER_USERNAME"])

    @property
    def atcoder_password(self) -> str:
        return str(self.config["ATCODER"]["ATCODER_PASSWORD"])