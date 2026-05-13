from netmiko import ConnectHandler

device = {
    'device_type': 'nokia_sros',  # Matches the driver in nokia_sros.py
    'host': '172.23.20.22',
    'username': 'admin',
    'password': 'NokiaSros1!',
    'port': 22,
    'verbose': True,  # Shows the connection process
}

with ConnectHandler(**device) as net_connect:
    print(f"Connected to: {net_connect.find_prompt()}")
    output = net_connect.send_command("show system information")
    print(output)
