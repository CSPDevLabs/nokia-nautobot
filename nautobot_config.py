import os
import sys

from nautobot.core.settings import *  # noqa F401,F403
from nautobot.core.settings_funcs import is_truthy, parse_redis_connection

if DATABASES["default"]["ENGINE"].endswith("mysql"):
    DATABASES["default"]["OPTIONS"] = {"charset": "utf8mb4"}

SECRET_KEY = os.getenv("NAUTOBOT_SECRET_KEY", ")4tli6$akj1a1li#kc+_!fpgk49=fkp-)f9tp6xn6*^83-zem7")

INSTALLATION_METRICS_ENABLED = is_truthy(os.getenv("NAUTOBOT_INSTALLATION_METRICS_ENABLED", "True"))