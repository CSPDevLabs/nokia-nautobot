from nornir import InitNornir
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result

nr = InitNornir(config_file="config.yaml")

# "get_facts" retrieves OS version, model, and serial number
results = nr.run(task=napalm_get, getters=["facts"])

print_result(results)

# To access the version string directly for a specific host:
# version = results["Router-01"][0].result["facts"]["os_version"]
