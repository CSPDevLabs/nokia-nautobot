FROM networktocode/nautobot:3.0-py3.13

RUN git clone https://github.com/CSPDevLabs/ntc-templates
RUN cd ntc-templates && pip install -e .

RUN git clone https://github.com/CSPDevLabs/nautobot-app-device-onboarding
RUN cd nautobot-app-device-onboarding && pip install -e .


RUN pip install \
#  nautobot-device-onboarding \
  nautobot-plugin-nornir \
  nautobot-ssot[infoblox] \
  nautobot-golden-config \
  netmiko \
  napalm \
  napalm-sros
