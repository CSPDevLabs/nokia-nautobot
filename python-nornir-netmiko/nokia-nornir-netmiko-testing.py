from nornir import InitNornir
from nornir_netmiko.tasks import netmiko_send_command
from nornir_utils.plugins.functions import print_result

# Initialize Nornir with your config files
nr = InitNornir(config_file="config.yaml")

def get_sros_info(task):
    # Runs the 'show version' command using the nokia_sros driver
    task.run(
        task=netmiko_send_command,
        command_string="show version"
    )

# Execute the task concurrently across all hosts
results = nr.run(task=get_sros_info)

# Output the results to the console
print_result(results)
