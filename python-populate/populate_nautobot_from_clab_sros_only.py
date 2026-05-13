#!/usr/bin/env python3

import yaml
import sys
import argparse
import re
import logging
import json
from datetime import datetime
import urllib3 # Import urllib3 to disable warnings

from napalm import get_network_driver
import pynautobot
from pynautobot.core.query import RequestError
from requests.exceptions import ConnectionError, RequestException

# Suppress InsecureRequestWarning globally
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -----------------------
# Custom JSON Formatter for logging
# -----------------------
class JsonFormatter(logging.Formatter):
    def format(self, record):
        # Start with base log record attributes
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "funcName": record.funcName,
            "lineno": record.lineno,
        }

        # Add attributes from the 'extra' dictionary, and other custom attributes
        # We need to be careful not to overwrite standard LogRecord attributes
        # that we want to keep (like funcName, lineno).
        # The 'name' attribute of LogRecord is the logger's name (e.g., '__main__').
        # We want to replace this with 'api_path' if it exists in 'extra'.

        # First, copy all non-standard attributes from the record to log_record
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                           'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                           'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                           'thread', 'threadName', 'processName', 'process', 'taskName',
                           'message'] and not key.startswith('_'):
                log_record[key] = value

        # Now, explicitly set the 'name' field in the JSON output
        # If 'api_path' was provided in extra (and thus copied to record.__dict__), use it.
        # Otherwise, fall back to the logger's name (record.name).
        log_record["name"] = getattr(record, "api_path", record.name)

        return json.dumps(log_record)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # Set default logging level to INFO

# Create console handler and set formatter
ch = logging.StreamHandler()
ch.setLevel(logging.INFO) # Console handler level
ch.setFormatter(JsonFormatter())

# Add the handler to the logger
logger.addHandler(ch)

# -----------------------
# Helpers
# -----------------------

def slugify(value):
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")

def get_or_create(endpoint, name, **kwargs):
    # Determine the Nautobot model type and API path for logging
    nautobot_model_type = getattr(endpoint, '_model_name', 'UnknownModel')
    api_path = getattr(endpoint, 'url', 'UnknownPath')

    try:
        obj = endpoint.get(name=name)
        if obj:
            logger.info(f"Found existing element: {name}", extra={
                "action": "found",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path, # This is correctly passed
                "entity_name": name
            })
            return obj

        if "slug" not in kwargs:
            kwargs["slug"] = slugify(name)

        new_obj = endpoint.create(name=name, **kwargs)
        logger.info(f"Successfully created element: {name}", extra={
                "action": "created",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path, # This is correctly passed
                "entity_name": name,
                "details": kwargs
            })
        return new_obj
    except RequestError as e:
        logger.error(f"Failed to get or create element: {name}. Reason: {e.message}", extra={
                "action": "failed",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path, # This is correctly passed
                "entity_name": name,
                "reason": e.message,
                "details": kwargs
            })
        return None
    except RequestException as e:
        logger.error(f"Network or API error for element: {name}. Reason: {e}", extra={
                "action": "failed",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path, # This is correctly passed
                "entity_name": name,
                "reason": str(e),
                "details": kwargs
            })
        return None

def get_or_create_status(nb, name, color, content_types):
    # For statuses, the model type is always 'extras.status' and path is fixed
    nautobot_model_type = 'extras.status'
    api_path = f"{nb.base_url}/api/extras/statuses/" # Construct path based on pynautobot base_url

    try:
        status = nb.extras.statuses.get(name=name)
        if status:
            logger.info(f"Found existing status: {name}", extra={
                "action": "found",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path, # This is correctly passed
                "entity_name": name
            })
            return status

        new_status = nb.extras.statuses.create(
            name=name,
            slug=slugify(name),
            color=color,
            content_types=content_types,
        )
        logger.info(f"Successfully created status: {name}", extra={
                "action": "created",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path, # This is correctly passed
                "entity_name": name,
                "details": {"color": color, "content_types": content_types}
            })
        return new_status
    except RequestError as e:
        logger.error(f"Failed to get or create status: {name}. Reason: {e.message}", extra={
                "action": "failed",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path, # This is correctly passed
                "entity_name": name,
                "reason": e.message
            })
        return None
    except RequestException as e:
        logger.error(f"Network or API error for status: {name}. Reason: {e}", extra={
                "action": "failed",
                "nautobot_model_type": nautobot_model_type,
                "api_path": api_path, # This is correctly passed
                "entity_name": name,
                "reason": str(e)
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
    parser.add_argument("--device-role", required=True)
    parser.add_argument("--no-verify-ssl", action="store_true", help="Disable SSL certificate verification.")
    args = parser.parse_args()

    # -----------------------
    # Nautobot connection
    # -----------------------
    try:
        nb = pynautobot.api(args.nautobot_url, token=args.nautobot_token)
        nb.http_session.verify = not args.no_verify_ssl
        logger.info(f"Connected to Nautobot {args.nautobot_url}", extra={"nautobot_url": args.nautobot_url, "ssl_verify": not args.no_verify_ssl})
    except ConnectionError as e:
        logger.critical(f"Connection failed to Nautobot: {e}", extra={"nautobot_url": args.nautobot_url, "error": str(e)})
        sys.exit(1)
    except RequestException as e:
        logger.critical(f"API connection error to Nautobot: {e}", extra={"nautobot_url": args.nautobot_url, "error": str(e)})
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
    location_status = get_or_create_status(
        nb, "Active", "4bb543", ["dcim.location"]
    )
    device_status = get_or_create_status(
        nb, "Active", "4bb543", ["dcim.device"]
    )
    ip_status = get_or_create_status(
        nb, "Active", "4bb543", ["ipam.ipaddress"]
    )
    cable_status = get_or_create_status(
        nb, "Connected", "00ff00", ["dcim.cable"]
    )

    if not all([location_status, device_status, ip_status, cable_status]):
        logger.critical("Failed to ensure all required statuses exist. Exiting.")
        sys.exit(1)

    # -----------------------
    # Core objects
    # -----------------------
    location_type = get_or_create(nb.dcim.location_types, "Site")
    if not location_type: sys.exit(1)

    location = get_or_create(
        nb.dcim.locations,
        args.site_name,
        location_type=location_type.id,
        status=location_status.id,
    )
    if not location: sys.exit(1)

    manufacturer = get_or_create(nb.dcim.manufacturers, "Nokia")
    if not manufacturer: sys.exit(1)

    platform = get_or_create(
        nb.dcim.platforms,
        args.platform_name,
        manufacturer=manufacturer.id,
    )
    if not platform: sys.exit(1)

    role = get_or_create(
        nb.dcim.device_roles,
        args.device_role,
        color="ff0000",
    )
    if not role: sys.exit(1)

    nautobot_devices = {}

    # -----------------------
    # Devices
    # -----------------------
    for name, node in nodes.items():
        if node.get("kind") != "nokia_srsim":
            continue

        mgmt_ip = node.get("mgmt-ipv4")
        model = node.get("type")

        device_type = nb.dcim.device_types.get(model=model)
        if not device_type:
            logger.warning(f"Skipping device {name}: DeviceType {model} not found in Nautobot.", extra={"action": "skipped", "nautobot_model_type": "dcim.device_type", "api_path": f"{nb.base_url}/api/dcim/device-types/", "entity_name": name, "reason": f"DeviceType {model} not found"})
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

        nb_dev = nb.dcim.devices.get(name=name)
        if not nb_dev:
            try:
                nb_dev = nb.dcim.devices.create(
                    name=name,
                    device_type=device_type.id,
                    device_role=role.id,
                    platform=platform.id,
                    location=location.id,
                    status=device_status.id,
                    serial=facts.get("serial_number"),
                )
                logger.info(f"Successfully created device: {name}", extra={"action": "created", "nautobot_model_type": "dcim.device", "api_path": f"{nb.base_url}/api/dcim/devices/", "entity_name": name, "details": {"device_type": device_type.id, "role": role.id, "platform": platform.id, "location": location.id, "serial": facts.get("serial_number")}})
            except RequestError as e:
                logger.error(f"Failed to create device: {name}. Reason: {e.message}", extra={"action": "failed", "nautobot_model_type": "dcim.device", "api_path": f"{nb.base_url}/api/dcim/devices/", "entity_name": name, "reason": e.message})
                continue
            except RequestException as e:
                logger.error(f"Network or API error creating device: {name}. Reason: {e}", extra={"action": "failed", "nautobot_model_type": "dcim.device", "api_path": f"{nb.base_url}/api/dcim/devices/", "entity_name": name, "reason": str(e)})
                continue
        else:
            logger.info(f"Found existing device: {name}", extra={"action": "found", "nautobot_model_type": "dcim.device", "api_path": f"{nb.base_url}/api/dcim/devices/", "entity_name": name})

        nautobot_devices[name] = nb_dev

        for iface, data in interfaces.items():
            if iface.lower().startswith("lo"):
                continue

            nb_iface = nb.dcim.interfaces.get(
                device_id=nb_dev.id,
                name=iface,
            )

            if not nb_iface:
                try:
                    nb_iface = nb.dcim.interfaces.create(
                        device=nb_dev.id,
                        name=iface,
                        type="10gbase-x-sfpp", # This might need to be dynamic based on actual interface type
                        enabled=data.get("is_enabled"),
                        mtu=data.get("mtu"),
                        mac_address=data.get("mac_address"),
                    )
                    logger.info(f"Successfully created interface {iface} on device {name}", extra={"action": "created", "nautobot_model_type": "dcim.interface", "api_path": f"{nb.base_url}/api/dcim/interfaces/", "device": name, "interface": iface, "details": {"type": "10gbase-x-sfpp", "enabled": data.get("is_enabled")}})
                except RequestError as e:
                    logger.error(f"Failed to create interface {iface} on device {name}. Reason: {e.message}", extra={"action": "failed", "nautobot_model_type": "dcim.interface", "api_path": f"{nb.base_url}/api/dcim/interfaces/", "device": name, "interface": iface, "reason": e.message})
                    continue
                except RequestException as e:
                    logger.error(f"Network or API error creating interface {iface} on device {name}. Reason: {e}", extra={"action": "failed", "nautobot_model_type": "dcim.interface", "api_path": f"{nb.base_url}/api/dcim/interfaces/", "device": name, "interface": iface, "reason": str(e)})
                    continue
            else:
                logger.info(f"Found existing interface {iface} on device {name}", extra={"action": "found", "nautobot_model_type": "dcim.interface", "api_path": f"{nb.base_url}/api/dcim/interfaces/", "device": name, "interface": iface})

            for fam in ips.get(iface, {}).values():
                for ip, _ in fam.items():
                    if "/" not in ip:
                        continue

                    nb_ip = nb.ipam.ip_addresses.get(address=ip)
                    if not nb_ip:
                        try:
                            nb_ip = nb.ipam.ip_addresses.create(
                                address=ip,
                                assigned_object_type="dcim.interface",
                                assigned_object_id=nb_iface.id,
                                status=ip_status.id,
                            )
                            logger.info(f"Successfully created IP address {ip} for interface {iface} on device {name}", extra={"action": "created", "nautobot_model_type": "ipam.ip_address", "api_path": f"{nb.base_url}/api/ipam/ip-addresses/", "device": name, "interface": iface, "ip_address": ip})
                        except RequestError as e:
                            logger.error(f"Failed to create IP address {ip} for interface {iface} on device {name}. Reason: {e.message}", extra={"action": "failed", "nautobot_model_type": "ipam.ip_address", "api_path": f"{nb.base_url}/api/ipam/ip-addresses/", "device": name, "interface": iface, "ip_address": ip, "reason": e.message})
                            continue
                        except RequestException as e:
                            logger.error(f"Network or API error creating IP address {ip} for interface {iface} on device {name}. Reason: {e}", extra={"action": "failed", "nautobot_model_type": "ipam.ip_address", "api_path": f"{nb.base_url}/api/ipam/ip-addresses/", "device": name, "interface": iface, "ip_address": ip, "reason": str(e)})
                            continue
                    else:
                        logger.info(f"Found existing IP address {ip} for interface {iface} on device {name}", extra={"action": "found", "nautobot_model_type": "ipam.ip_address", "api_path": f"{nb.base_url}/api/ipam/ip-addresses/", "device": name, "interface": iface, "ip_address": ip})

    # -----------------------
    # Cables
    # -----------------------
    for link in links:
        ep1, ep2 = link["endpoints"]
        n1, i1 = ep1.split(":")
        n2, i2 = ep2.split(":")

        if n1 not in nautobot_devices or n2 not in nautobot_devices:
            logger.warning(f"Skipping link between {ep1} and {ep2}: One or both devices not found in Nautobot.", extra={"action": "skipped", "nautobot_model_type": "dcim.cable", "api_path": f"{nb.base_url}/api/dcim/cables/", "endpoint1": ep1, "endpoint2": ep2, "reason": "Device not found"})
            continue

        d1 = nautobot_devices[n1]
        d2 = nautobot_devices[n2]

        iface1 = nb.dcim.interfaces.get(device_id=d1.id, name=i1)
        iface2 = nb.dcim.interfaces.get(device_id=d2.id, name=i2)

        if not iface1:
            logger.warning(f"Skipping link between {ep1} and {ep2}: Interface {i1} not found on device {n1}.", extra={"action": "skipped", "nautobot_model_type": "dcim.cable", "api_path": f"{nb.base_url}/api/dcim/cables/", "device": n1, "interface": i1, "reason": "Interface not found"})
            continue
        if not iface2:
            logger.warning(f"Skipping link between {ep1} and {ep2}: Interface {i2} not found on device {n2}.", extra={"action": "skipped", "nautobot_model_type": "dcim.cable", "api_path": f"{nb.base_url}/api/dcim/cables/", "device": n2, "interface": i2, "reason": "Interface not found"})
            continue

        # Check if cable already exists (either direction)
        existing_cable = nb.dcim.cables.filter(
            termination_a_id=iface1.id,
            termination_b_id=iface2.id,
        ) or nb.dcim.cables.filter(
            termination_b_id=iface1.id,
            termination_a_id=iface2.id,
        )

        if not existing_cable:
            try:
                nb.dcim.cables.create(
                    termination_a_type="dcim.interface",
                    termination_a_id=iface1.id,
                    termination_b_type="dcim.interface",
                    termination_b_id=iface2.id,
                    status=cable_status.id,
                )
                logger.info(f"Successfully created cable between {ep1} and {ep2}", extra={"action": "created", "nautobot_model_type": "dcim.cable", "api_path": f"{nb.base_url}/api/dcim/cables/", "endpoint1": ep1, "endpoint2": ep2})
            except RequestError as e:
                logger.error(f"Failed to create cable between {ep1} and {ep2}. Reason: {e.message}", extra={"action": "failed", "nautobot_model_type": "dcim.cable", "api_path": f"{nb.base_url}/api/dcim/cables/", "endpoint1": ep1, "endpoint2": ep2, "reason": e.message})
                continue
            except RequestException as e:
                logger.error(f"Network or API error creating cable between {ep1} and {ep2}. Reason: {e}", extra={"action": "failed", "nautobot_model_type": "dcim.cable", "api_path": f"{nb.base_url}/api/dcim/cables/", "endpoint1": ep1, "endpoint2": ep2, "reason": str(e)})
                continue
        else:
            logger.info(f"Found existing cable between {ep1} and {ep2}", extra={"action": "found", "nautobot_model_type": "dcim.cable", "api_path": f"{nb.base_url}/api/dcim/cables/", "endpoint1": ep1, "endpoint2": ep2})

    logger.info("Nautobot population complete", extra={"status": "complete"})

if __name__ == "__main__":
    main()