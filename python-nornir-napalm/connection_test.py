from napalm import get_network_driver
driver = get_network_driver('sros')
device = driver('172.23.20.22', 'admin', 'NokiaSros1!')
device.open()
print(device.get_facts())
device.close()
