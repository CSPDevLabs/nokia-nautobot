#!/usr/bin/env python3

import yaml
import argparse
import re
import logging
import json
from datetime import datetime
import urllib3
import requests
from collections import defaultdict, deque

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -----------------------
# JSON Logger
# -----------------------
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "funcName": record.funcName,
            "lineno": record.lineno,
            "name": getattr(record, "api_path", record.name),
        }
        for k, v in record.__dict__.items():
            if k not in log_record and not k.startswith("_"):
                log_record[k] = v
        return json.dumps(log_record)

logger = logging.getLogger("nautobot-loader")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)

# -----------------------
# Helpers
# -----------------------
def slugify(value):
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")

def topo_sort(items):
    graph = defaultdict(list)
    indegree = defaultdict(int)

    for node, parent in items.items():
        if parent:
            graph[parent].append(node)
            indegree[node] += 1
        indegree.setdefault(node, 0)

    queue = deque([n for n in indegree if indegree[n] == 0])
    order = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for child in graph[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    return order

# -----------------------
# API Client
# -----------------------
class NautobotAPIClient:
    def __init__(self, base_url, token, verify_ssl, api_config):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.api = api_config["api_endpoints"]
        self.headers = {
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Cache for content types to avoid repeated API calls
        self._content_type_cache = {}

    def request(self, method, endpoint, params=None, data=None, obj_id=None):
        ep = self.api[endpoint]
        url = f"{self.base_url}{ep['path']}"
        if obj_id:
            url += f"{obj_id}/"

        r = requests.request(
            method,
            url,
            headers=self.headers,
            params=params,
            json=data,
            verify=self.verify_ssl,
            timeout=30,
        )

        if method == "DELETE":
            return r.status_code == 204

        r.raise_for_status()
        return r.json()

    def get(self, endpoint, params):
        r = self.request("GET", endpoint, params=params)
        return r["results"][0] if r.get("results") else None

    def create(self, endpoint, data):
        return self.request("POST", endpoint, data=data)

    def delete(self, endpoint, obj_id):
        return self.request("DELETE", endpoint, obj_id=obj_id)

    def resolve_value(self, resolver_type, value):
        if resolver_type == "content_type":
            if value in self._content_type_cache:
                return self._content_type_cache[value]

            try:
                # First, try to get all content types if cache is empty
                if not self._content_type_cache:
                    data = self.request("GET", "content_types", params={})
                    for ct in data.get("results", []):
                        key = f"{ct['app_label']}.{ct['model']}"
                        self._content_type_cache[key] = ct["id"]
                
                if value in self._content_type_cache:
                    return self._content_type_cache[value]
                
                raise RuntimeError(f"Content type '{value}' not found.")

            except Exception as e:
                logger.error(f"Error resolving content type '{value}': {e}", exc_info=True)
                raise RuntimeError(
                    f"Content type endpoint not available or resolution failed for '{value}': {e}"
                )

        raise RuntimeError(f"Unknown resolver type: {resolver_type}")

# -----------------------
# Generic Object Engine
# -----------------------
def process_objects(nb, endpoint, objects, remove=False):
    if isinstance(objects, dict):
        objects = [objects]

    ep = nb.api[endpoint]
    lookup_key = ep["get_params"][0]
    created = {}

    # Build hierarchy
    parents = {
        o.get(lookup_key): o.get("parent")
        for o in objects
        if isinstance(o, dict) and o.get(lookup_key)
    }

    order = topo_sort(parents)
    if remove:
        order = reversed(order)

    for key in order:
        obj = next(o for o in objects if o.get(lookup_key) == key)
        entity_name = obj.get("name", key)

        existing = nb.get(endpoint, {lookup_key: key})

        if remove:
            if existing:
                nb.delete(endpoint, existing["id"])
                logger.info("Deleted", extra={"endpoint": endpoint, "entity": entity_name})
            continue

        if existing:
            created[key] = existing
            logger.info("Found", extra={"endpoint": endpoint, "entity": entity_name})
            continue

        payload = {}

        for param in ep["create_params"]:

            # -----------------
            # String param
            # -----------------
            if isinstance(param, str):
                if param == "slug":
                    payload[param] = obj.get("slug", slugify(key))
                elif param == "parent" and obj.get("parent"):
                    payload[param] = created[obj["parent"]]["id"]                   
                elif param in obj:
                    payload[param] = obj[param]

            # -----------------
            # Dict param
            # -----------------
            elif isinstance(param, dict):
                field, cfg = next(iter(param.items()))

                # Case 1: simple field declared as dict (e.g., parent: None)
                if cfg is None:
                    if field == "parent" and obj.get("parent"):
                        payload[field] = created[obj["parent"]]["id"]
                    elif field in obj:
                        payload[field] = obj[field]
                    continue

                # Case 2: Field requires resolution (e.g., endpoint/lookup)

                if "endpoint" in cfg and "lookup" in cfg:
                    value = obj.get(field)
                    if not value:
                        continue
                    if cfg.get("many"):
                        ids = []
                        for v in value:
                            ref = nb.get(cfg["endpoint"], {cfg["lookup"]: v})
                            if not ref:
                                # FIX: Use !r to safely represent string variables in f-string
                                raise RuntimeError(
                                    f"Missing dependency: {cfg['endpoint']!r} "
                                    f"{cfg['lookup']!r}={v!r}"
                                )
                            ids.append(ref["id"])
                        payload[field] = ids
                    else:
                        ref = nb.get(cfg["endpoint"], {cfg["lookup"]: value})
                        if not ref:
                            # FIX: Use !r to safely represent string variables in f-string
                            raise RuntimeError(
                                f"Missing dependency: {cfg['endpoint']!r} "
                                f"{cfg['lookup']!r}={value!r}"
                            )
                        payload[field] = ref["id"]
                    continue

                # Case 3: Field requires 'resolve' logic (e.g., content_types)
                if "resolve" in cfg:
                    resolver_cfg = cfg["resolve"]
                    resolver_type = resolver_cfg["type"]
                    
                    resolved_ids = []
                    # Prioritize values from the initial_data.json object
                    if field in obj and obj[field] is not None:
                        items_to_resolve = obj[field]
                        # Ensure it's iterable, even if a single string is provided in JSON
                        if not isinstance(items_to_resolve, list):
                            items_to_resolve = [items_to_resolve]
                    # Fallback to static value(s) from api_config.yaml if not in object
                    elif "value" in resolver_cfg:
                        items_to_resolve = resolver_cfg["value"]
                        # Ensure it's iterable, even if a single string is provided in YAML
                        if not isinstance(items_to_resolve, list):
                            items_to_resolve = [items_to_resolve]
                    else:
                        items_to_resolve = [] # No values to resolve

                    for item_to_resolve in items_to_resolve:
                        resolved_ids.append(nb.resolve_value(resolver_type, item_to_resolve))
                    
                    if resolved_ids: # Only add to payload if there are values
                        payload[field] = resolved_ids
                    continue

                raise RuntimeError(f"Invalid create_param config: {param}")

        new = nb.create(endpoint, payload)
        created[key] = new
        logger.info("Created", extra={"endpoint": endpoint, "entity": entity_name})

    return created

# -----------------------
# Main
# -----------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nautobot-url", required=True)
    parser.add_argument("--nautobot-token", required=True)
    parser.add_argument("--initial-data-file", required=True)
    parser.add_argument("--api-config-file", required=True)
    parser.add_argument("--remove-all", action="store_true")
    parser.add_argument("--no-verify-ssl", action="store_true")
    args = parser.parse_args()

    api_cfg = yaml.safe_load(open(args.api_config_file))
    data = json.load(open(args.initial_data_file))

    # Ensure 'content_types' endpoint is defined in api_cfg for resolution
    if 'content_types' not in api_cfg['api_endpoints']:
        api_cfg['api_endpoints']['content_types'] = {
            'path': '/api/extras/content-types/', # Standard Nautobot path
            'model_name': 'extras.contenttype',
            'get_params': ['app_label', 'model'] # Not strictly used for this resolution, but good practice
        }

    nb = NautobotAPIClient(
        args.nautobot_url,
        args.nautobot_token,
        not args.no_verify_ssl,
        api_cfg,
    )

    endpoints = list(api_cfg["api_endpoints"].keys())

    if args.remove_all:
        endpoints = reversed(endpoints)

    for endpoint in endpoints:
        if endpoint not in data:
            continue
        process_objects(nb, endpoint, data[endpoint], remove=args.remove_all)

    logger.info("Completed", extra={"remove_all": args.remove_all})

if __name__ == "__main__":
    main()