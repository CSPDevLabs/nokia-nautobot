FROM networktocode/nautobot:3.0-py3.13
RUN pip install nautobot-device-onboarding \
  nautobot-plugin-nornir \
  nautobot-ssot[infoblox] \
  netmiko \
  napalm \
  napalm-sros
