#!/usr/bin/env python3

import yaml
import sys
import argparse
import re
import logging
import json
from datetime import datetime
import urllib3
import requests # Import the requests library

from napalm import get_network_driver
# pynautobot and its exceptions are no longer needed
# from pynautobot.core.query import RequestError
# from requests.exceptions import ConnectionError, RequestException

# Suppress InsecureRequestWarning globally
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -----------------------
# Custom JSON Formatter for logging
# -----------------------
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "funcName": record.funcName,
            "lineno": record.lineno,
        }

        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                           'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                           'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                           'thread', 'threadName', 'processName', 'process', 'taskName',
                           'message'] and not key.startswith('_'):
                log_record[key] = value

        log_record["name"] = getattr(record, "api_path", record.name)

        return json.dumps(log_record)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(JsonFormatter())
logger.addHandler(ch)

# -----------------------
# Nautobot API Client (replaces pynautobot)
# -----------------------
class NautobotAPIClient:
    def __init__(self, base_url, token, verify_ssl, api_config):
        self.base_url = base_url.rstrip('/')
        self.headers = {
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.verify_ssl = verify_ssl
        self.api_config = api_config

    def _request(self, method, endpoint_key, params=None, data=None, item_id=None):
        if endpoint_key not in self.api_config['api_endpoints']:
            raise ValueError(f"API endpoint '{endpoint_key}' not found in configuration.")

        endpoint_info = self.api_config['api_endpoints'][endpoint_key]
        path = endpoint_info['path']
        full_url = f"{self.base_url}{path}"
        if item_id:
            full_url = f"{full_url}{item_id}/" # For GET by ID, PUT, DELETE

        try:
            response = requests.request(
                method,
                full_url,
                headers=self.headers,
                params=params,
                json=data,
                verify=self.verify_ssl,
                timeout=30 # Add a timeout for requests
            )
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            return response.json()
        except requests.exceptions.ConnectionError as e:
            logger.critical(f"Connection failed to Nautobot: {e}", extra={"nautobot_url": self.base_url, "error": str(e)})
            sys.exit(1)
        except requests.exceptions.Timeout:
            logger.critical(f"Request to Nautobot timed out for {full_url}", extra={"nautobot_url": self.base_url, "error": "Timeout"})
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            error_message = f"API error for {method} {full_url}: {e}"
            if e.response is not None:
                try:
                    error_details = e.response.json()
                    error_message += f" - Details: {error_details}"
                except json.JSONDecodeError:
                    error_message += f" - Response: {e.response.text}"
            logger.error(error_message, extra={"nautobot_url": self.base_url, "error": str(e), "status_code": e.response.status_code if e.response else 'N/A'})
            return None # Return None on API errors

    def get(self, endpoint_key, query_params=None):
        response = self._request("GET", endpoint_key, params=query_params)
        if response and response.get('results'):
            # Nautobot API typically returns a list of results for GET requests
            # We assume 'get' is often used to find a single item by name/slug
            # If multiple items match, we return the first one.
            return response['results'][0]
        return None

    def create(self, endpoint_key, data):
        return self._request("POST", endpoint_key, data=data)

    def filter(self, endpoint_key, query_params=None):
        response = self._request("GET", endpoint_key, params=query_params)
        if response and response.get('results'):
            return response['results']
        return []

# -----------------------
# Helpers
# -----------------------

def slugify(value):
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")

def get_or_create_nautobot_object(nb_client, endpoint_key, name_or_model, **kwargs):
    endpoint_info = nb_client.api_config['api_endpoints'][endpoint_key]
    nautobot_model_type = endpoint_info['model_name']
    api_path = f"{nb_client.base_url}{endpoint_info['path']}"

    # Determine lookup parameter based on endpoint_key
    lookup_param = 'name'
    if endpoint_key == 'device_types':
        lookup_param = 'model' # DeviceType uses 'model' for lookup in this script

    query_params = {lookup_param: name_or_model}

    try:
        obj = nb_client.get(endpoint_key, query_params=query_params)
        if obj:
            logger.info(f"Found existing element: {name_or_model} ({endpoint_key})", extra={
                "action": "found",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path,
                "entity_name": name_or_model
            })
            return obj

        # Prepare data for creation
        create_data = {lookup_param: name_or_model} # Start with the name/model
        if "slug" not in kwargs and 'slug' in endpoint_info.get('create_params', []):
            create_data["slug"] = slugify(name_or_model)
        
        # Add other kwargs, ensuring they are in the create_params if specified
        for k, v in kwargs.items():
            if k in endpoint_info.get('create_params', []):
                create_data[k] = v
            else:
                logger.debug(f"Warning: '{k}' not listed in create_params for {endpoint_key}. Adding anyway.", extra={"key": k, "endpoint": endpoint_key})
        
        new_obj = nb_client.create(endpoint_key, data=create_data)
        if new_obj:
            logger.info(f"Successfully created element: {name_or_model} ({endpoint_key})", extra={
                    "action": "created",
                    "nautobot_model_type": nautobot_model_type,
                    "api_path": api_path,
                    "entity_name": name_or_model,
                    "details": create_data
                })
            return new_obj
        else:
            logger.error(f"Failed to create element: {name_or_model} ({endpoint_key}). API returned no object.", extra={
                "action": "failed",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path,
                "entity_name": name_or_model,
                "reason": "API returned no object after creation attempt",
                "details": create_data
            })
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"API error for element: {name_or_model} ({endpoint_key}). Reason: {e}", extra={
                "action": "failed",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path,
                "entity_name": name_or_model,
                "reason": str(e),
                "details": kwargs
            })
        return None
    except ValueError as e:
        logger.error(f"Configuration error for element: {name_or_model} ({endpoint_key}). Reason: {e}", extra={
                "action": "failed",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path,
                "entity_name": name_or_model,
                "reason": str(e),
                "details": kwargs
            })
        return None

# -----------------------
# Main
# -----------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("topology_file")
    parser.add_argument("--nautobot-url", required=True)
    parser.add_argument("--nautobot-token", required=True)
    parser.add_argument("--sros-username", required=True)
    parser.add_argument("--sros-password", required=True)
    parser.add_argument("--site-name", required=True)
    parser.add_argument("--platform-name", required=True)
    # parser.add_argument("--device-role", required=True) # This line has been removed
    parser.add_argument("--no-verify-ssl", action="store_true", help="Disable SSL certificate verification.")
    parser.add_argument("--api-config-file", default="nautobot_api_config.yaml", help="Path to the Nautobot API configuration YAML file.")
    args = parser.parse_args()

    # -----------------------
    # Load API Configuration
    # -----------------------
    try:
        with open(args.api_config_file) as f:
            api_config = yaml.safe_load(f)
        logger.info(f"Successfully loaded API configuration from: {args.api_config_file}", extra={"file": args.api_config_file})
    except FileNotFoundError:
        logger.critical(f"API configuration file not found: {args.api_config_file}", extra={"file": args.api_config_file})
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.critical(f"Error parsing API configuration YAML file: {e}", extra={"file": args.api_config_file, "error": str(e)})
        sys.exit(1)

    # -----------------------
    # Nautobot connection (using custom client)
    # -----------------------
    try:
        nb_client = NautobotAPIClient(args.nautobot_url, args.nautobot_token, not args.no_verify_ssl, api_config)
        # Test connection by trying to get a basic endpoint (e.g., /api/status/)
        # This is a simple way to check if the URL and token are valid.
        status_check = nb_client._request("GET", "statuses", params={"limit": 1}) # Use an existing endpoint for a quick check
        if status_check is None:
             raise requests.exceptions.RequestException("Initial API connection check failed.")
        logger.info(f"Connected to Nautobot {args.nautobot_url}", extra={"nautobot_url": args.nautobot_url, "ssl_verify": not args.no_verify_ssl})
    except (requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
        logger.critical(f"Failed to connect or authenticate to Nautobot: {e}", extra={"nautobot_url": args.nautobot_url, "error": str(e)})
        sys.exit(1)

    # -----------------------
    # Load topology
    # -----------------------
    try:
        with open(args.topology_file) as f:
            topo = yaml.safe_load(f)
        logger.info(f"Successfully loaded topology file: {args.topology_file}", extra={"file": args.topology_file})
    except FileNotFoundError:
        logger.critical(f"Topology file not found: {args.topology_file}", extra={"file": args.topology_file})
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.critical(f"Error parsing topology YAML file: {e}", extra={"file": args.topology_file, "error": str(e)})
        sys.exit(1)

    nodes = topo.get("nodes", {})
    links = topo.get("links", [])

    # -----------------------
    # Required statuses
    # -----------------------
    # Note: For statuses, content_types need to be resolved to their IDs or full string identifiers
    # For simplicity, we'll use the string identifiers as they are often accepted by Nautobot API
    # You might need to fetch content_type IDs if the API strictly requires them.
    # Example: content_type = nb_client.get('content_types', {'app_label': 'dcim', 'model': 'location'})['id']
    
    location_status = get_or_create_nautobot_object(
        nb_client, "statuses", "Active", color="4bb543", content_types=["dcim.location"]
    )
    device_status = get_or_create_nautobot_object(
        nb_client, "statuses", "Active", color="4bb543", content_types=["dcim.device"]
    )
    ip_status = get_or_create_nautobot_object(
        nb_client, "statuses", "Active", color="4bb543", content_types=["ipam.ipaddress"]
    )
    cable_status = get_or_create_nautobot_object(
        nb_client, "statuses", "Connected", color="00ff00", content_types=["dcim.cable"]
    )

    if not all([location_status, device_status, ip_status, cable_status]):
        logger.critical("Failed to ensure all required statuses exist. Exiting.")
        sys.exit(1)

    # -----------------------
    # Core objects
    # -----------------------
    location_type = get_or_create_nautobot_object(nb_client, "location_types", "Site")
    if not location_type: sys.exit(1)

    location = get_or_create_nautobot_object(
        nb_client,
        "locations",
        args.site_name,
        location_type=location_type['id'], # Use ['id'] as objects are now dicts
        status=location_status['id'],
    )
    if not location: sys.exit(1)

    manufacturer = get_or_create_nautobot_object(nb_client, "manufacturers", "Nokia")
    if not manufacturer: sys.exit(1)

    platform = get_or_create_nautobot_object(
        nb_client,
        "platforms",
        args.platform_name,
        manufacturer=manufacturer['id'],
    )
    if not platform: sys.exit(1)

    nautobot_devices = {}

    # -----------------------
    # Devices
    # -----------------------
    for name, node in nodes.items():
        if node.get("kind") != "nokia_srsim":
            continue

        mgmt_ip = node.get("mgmt-ipv4")
        model = node.get("type")

        # Lookup device_type by 'model' as specified in YAML
        device_type = nb_client.get("device_types", query_params={"model": model})
        if not device_type:
            logger.warning(f"Skipping device {name}: DeviceType {model} not found in Nautobot.", extra={"action": "skipped", "nautobot_model_type": "dcim.device_type", "api_path": f"{nb_client.base_url}/api/dcim/device-types/", "entity_name": name, "reason": f"DeviceType {model} not found"})
            continue

        logger.info(f"Collecting data from device: {name}", extra={"action": "data_collection", "device_name": name, "mgmt_ip": mgmt_ip})

        try:
            driver = get_network_driver("nokia_sros")
            dev = driver(
                hostname=mgmt_ip,
                username=args.sros_username,
                password=args.sros_password,
            )

            dev.open()
            facts = dev.get_facts()
            interfaces = dev.get_interfaces()
            ips = dev.get_interfaces_ip()
            dev.close()
            logger.info(f"Successfully collected data from device: {name}", extra={"action": "data_collected", "device_name": name})
        except Exception as e:
            logger.error(f"Failed to collect data from device {name} via NAPALM. Reason: {e}", extra={"action": "data_collection_failed", "device_name": name, "reason": str(e)})
            continue

        nb_dev = nb_client.get("devices", query_params={"name": name})
        if not nb_dev:
            nb_dev = get_or_create_nautobot_object(
                nb_client,
                "devices",
                name,
                device_type=device_type['id'],
                device_role=role['id'], # Using the 'role' object obtained above
                platform=platform['id'],
                location=location['id'],
                status=device_status['id'],
                serial=facts.get("serial_number"),
            )
            if not nb_dev: continue # Skip if device creation failed
        else:
            logger.info(f"Found existing device: {name}", extra={"action": "found", "nautobot_model_type": "dcim.device", "api_path": f"{nb_client.base_url}/api/dcim/devices/", "entity_name": name})

        nautobot_devices[name] = nb_dev

        for iface_name, data in interfaces.items():
            if iface_name.lower().startswith("lo"):
                continue

            nb_iface = nb_client.get("interfaces", query_params={"device_id": nb_dev['id'], "name": iface_name})

            if not nb_iface:
                nb_iface = get_or_create_nautobot_object(
                    nb_client,
                    "interfaces",
                    iface_name, # name parameter
                    device=nb_dev['id'],
                    type="10gbase-x-sfpp", # This might need to be dynamic based on actual interface type
                    enabled=data.get("is_enabled"),
                    mtu=data.get("mtu"),
                    mac_address=data.get("mac_address"),
                )
                if not nb_iface: continue # Skip if interface creation failed
            else:
                logger.info(f"Found existing interface {iface_name} on device {name}", extra={"action": "found", "nautobot_model_type": "dcim.interface", "api_path": f"{nb_client.base_url}/api/dcim/interfaces/", "device": name, "interface": iface_name})

            for fam in ips.get(iface_name, {}).values():
                for ip_address, _ in fam.items():
                    if "/" not in ip_address:
                        continue

                    nb_ip = nb_client.get("ip_addresses", query_params={"address": ip_address})
                    if not nb_ip:
                        nb_ip = get_or_create_nautobot_object(
                            nb_client,
                            "ip_addresses",
                            ip_address, # address parameter
                            assigned_object_type="dcim.interface",
                            assigned_object_id=nb_iface['id'],
                            status=ip_status['id'],
                        )
                        if not nb_ip: continue # Skip if IP creation failed
                    else:
                        logger.info(f"Found existing IP address {ip_address} for interface {iface_name} on device {name}", extra={"action": "found", "nautobot_model_type": "ipam.ip_address", "api_path": f"{nb_client.base_url}/api/ipam/ip-addresses/", "device": name, "interface": iface_name, "ip_address": ip_address})

    # -----------------------
    # Cables
    # -----------------------
    for link in links:
        ep1, ep2 = link["endpoints"]
        n1, i1 = ep1.split(":")
        n2, i2 = ep2.split(":")

        if n1 not in nautobot_devices or n2 not in nautobot_devices:
            logger.warning(f"Skipping link between {ep1} and {ep2}: One or both devices not found in Nautobot.", extra={"action": "skipped", "nautobot_model_type": "dcim.cable", "api_path": f"{nb_client.base_url}/api/dcim/cables/", "endpoint1": ep1, "endpoint2": ep2, "reason": "Device not found"})
            continue

        d1 = nautobot_devices[n1]
        d2 = nautobot_devices[n2]

        iface1 = nb_client.get("interfaces", query_params={"device_id": d1['id'], "name": i1})
        iface2 = nb_client.get("interfaces", query_params={"device_id": d2['id'], "name": i2})

        if not iface1:
            logger.warning(f"Skipping link between {ep1} and {ep2}: Interface {i1} not found on device {n1}.", extra={"action": "skipped", "nautobot_model_type": "dcim.cable", "api_path": f"{nb_client.base_url}/api/dcim/cables/", "device": n1, "interface": i1, "reason": "Interface not found"})
            continue
        if not iface2:
            logger.warning(f"Skipping link between {ep1} and {ep2}: Interface {i2} not found on device {n2}.", extra={"action": "skipped", "nautobot_model_type": "dcim.cable", "api_path": f"{nb_client.base_url}/api/dcim/cables/", "device": n2, "interface": i2, "reason": "Interface not found"})
            continue

        # Check if cable already exists (either direction)
        # Nautobot API filter for cables by termination IDs
        existing_cable = nb_client.filter(
            "cables",
            query_params={
                "termination_a_id": iface1['id'],
                "termination_b_id": iface2['id'],
            }
        )
        if not existing_cable:
            existing_cable = nb_client.filter(
                "cables",
                query_params={
                    "termination_a_id": iface2['id'],
                    "termination_b_id": iface1['id'],
                }
            )

        if not existing_cable:
            created_cable = nb_client.create(
                "cables",
                data={
                    "termination_a_type": "dcim.interface",
                    "termination_a_id": iface1['id'],
                    "termination_b_type": "dcim.interface",
                    "termination_b_id": iface2['id'],
                    "status": cable_status['id'],
                }
            )
            if created_cable:
                logger.info(f"Successfully created cable between {ep1} and {ep2}", extra={"action": "created", "nautobot_model_type": "dcim.cable", "api_path": f"{nb_client.base_url}/api/dcim/cables/", "endpoint1": ep1, "endpoint2": ep2})
            else:
                logger.error(f"Failed to create cable between {ep1} and {ep2}. API returned no object.", extra={"action": "failed", "nautobot_model_type": "dcim.cable", "api_path": f"{nb_client.base_url}/api/dcim/cables/", "endpoint1": ep1, "endpoint2": ep2, "reason": "API returned no object after creation attempt"})
        else:
            logger.info(f"Found existing cable between {ep1} and {ep2}", extra={"action": "found", "nautobot_model_type": "dcim.cable", "api_path": f"{nb_client.base_url}/api/dcim/cables/", "endpoint1": ep1, "endpoint2": ep2})

    logger.info("Nautobot population complete", extra={"status": "complete"})

if __name__ == "__main__":
    main()