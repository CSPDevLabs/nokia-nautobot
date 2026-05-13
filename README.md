# Nautobot Deployment on Kind Kubernetes Cluster

This guide outlines the process for deploying Nautobot on a local Kind Kubernetes cluster using Helm, configuring it with external PostgreSQL and Redis databases, and accessing the deployed instance.

## Table of Contents

1.  [Prerequisites](#prerequisites)
2.  [Kind Cluster Setup](#kind-cluster-setup)
3.  [External Database Setup](#external-database-setup)
4.  [Nautobot Helm Deployment](#nautobot-helm-deployment)
5.  [Accessing Nautobot](#accessing-nautobot)
6.  [Configuration Details (`values-ext-db.yaml`)](#configuration-details-values-ext-dbyaml)

## 1. Prerequisites

Ensure you have the following tools available. Note that `helm` and `kubectl` are expected to be in a `./tools` folder relative to your working directory.

*   **`kind`:** For creating local Kubernetes clusters.
*   **`make`:** To run the `try-nautobot` command.
*   **`helm`:** Helm package manager (located in `./tools`).
*   **`kubectl`:** Kubernetes command-line tool (located in `./tools`).

## 2. Kind Cluster Setup

Start by creating a Kind Kubernetes cluster, which will serve as your playground environment for Nautobot.

```bash
make try-nautobot
```
This command is expected to set up a Kind cluster and configure your kubectl context to use it.

## 3. External Database Setup

Nautobot will be configured to use external PostgreSQL and Redis instances. Apply the provided postg-redis.yaml to deploy these services within your cluster.

```bash
kubectl apply -f postg-redis.yaml
```
## 4. Nautobot Helm Deployment

Deploy Nautobot using its official Helm chart, overriding default values with values-ext-db.yaml to configure external databases and adjust resource limits.

### 4.1. Add Nautobot Helm Repository

```bash
helm repo add nautobot https://nautobot.github.io/helm-charts/
helm repo update
```

### 4.2. Generate Default Values (Optional)

You can inspect the default Helm chart values:

```bash
helm show values nautobot/nautobot > values-default.yaml
```

### 4.3. Install Nautobot

Install Nautobot using your custom values-ext-db.yaml file.

```bash
helm install nautobot nautobot/nautobot -f values-ext-db.yaml
```

### 4.4. Install Credentials (extraEnvVarsSecret)

```bash
kubectl apply -f nokia-secrets.yaml
```

## 5. Accessing Nautobot

Once Nautobot is deployed, use the following commands to access the web interface and retrieve credentials.

### 5.1. Get the Nautobot URL

```bash
kubectl port-forward --namespace default svc/nautobot-default --address 0.0.0.0 8080:80
kubectl port-forward --namespace default svc/nautobot-default --address 0.0.0.0 8443:443
```

After running the kubectl port-forward command, open your web browser and navigate to `http://<localhost-or-your-host-ip>:8080`

### 5.2. Get Nautobot Admin Credentials

```bash
echo "Username: admin"
echo "Password: $(kubectl get secret --namespace default nautobot-env -o jsonpath="{.data.NAUTOBOT_SUPERUSER_PASSWORD}" | base64 --decode)"
echo "API Token: $(kubectl get secret --namespace default nautobot-env -o jsonpath="{.data.NAUTOBOT_SUPERUSER_API_TOKEN}" | base64 --decode)"
```

### 5.3. Retrieve Nautobot Secret Key

```bash
echo "Secret Key: $(kubectl get secret --namespace default nautobot-env -o jsonpath="{.data.NAUTOBOT_SECRET_KEY}" | base64 --decode)"
```

## 6. Configuration Details (values-ext-db.yaml)

The `values-ext-db.yaml` file contains critical overrides for resource allocation, external database connections, and Nautobot's internal configuration.

## 8. Troubleshooting

### 8.1 Checking reachibility to an IP and port
Execute: `kubectl exec -ti <nautobot-pod> -- nautobot-server shell_plus`


```python
import socket

def is_reachable(ip, port=830, timeout=2):
    """
    Checks if a specific port on an IP is reachable.
    Common ports: 830 (NetConf), 22 (SSH).
    """
    try:
        # socket.create_connection handles the lookup and connection attempt
        with socket.create_connection((ip, port), timeout=timeout):
            print(f"✅ {ip}:{port} is REACHABLE.")
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        print(f"❌ {ip}:{port} is NOT reachable.")
        return False

# Test it
is_reachable('172.18.0.12', port=830)  # Test reacheability to NC port
```

### 8.2 Test Env Vars

Execute: `kubectl exec -ti <nautobot-pod> -- nautobot-server nbshell`

```python
import os
print(os.getenv('NOKIA_NETCONF_USER'))
```

### 8.3 Checking Secret Group

```python
from nautobot.extras.models import SecretsGroup
from nautobot.extras.choices import SecretsGroupAccessTypeChoices, SecretsGroupSecretTypeChoices

group_name = 'nokia-sros-secret'
group = SecretsGroup.objects.get(name=group_name)

mapping_nc = group.secrets_group_associations.filter(
    access_type=SecretsGroupAccessTypeChoices.TYPE_NETCONF,
    secret_type=SecretsGroupSecretTypeChoices.TYPE_PASSWORD
).first()

mapping_ssh = group.secrets_group_associations.filter(
    access_type=SecretsGroupAccessTypeChoices.TYPE_SSH,
    secret_type=SecretsGroupSecretTypeChoices.TYPE_PASSWORD
).first()

if mapping_nc:
    secret = mapping_nc.secret
    print(f"✅ Group is using: {secret.name} (ID: {secret.id}) for NETCONF")
    print(f"✅ Provider: {secret.provider}")
    
    # Check if the environment variable is actually readable
    val = secret.get_value()
    print(f"✅ Resolved Valuefor NETCONF: {val if val else 'MISSING/EMPTY'} for NETCONF")
else:
    print(f"❌ No NETCONF Password mapping_nc found.")

if mapping_ssh:
    secret = mapping_ssh.secret
    print(f"✅ Group is using: {secret.name} (ID: {secret.id}) for SSH")
    print(f"✅ Provider: {secret.provider} for SSH")
    
    # Check if the environment variable is actually readable
    val = secret.get_value()
    print(f"✅ Resolved Value for SSH: {val if val else 'MISSING/EMPTY'}")
else:
    print(f"❌ No SSH Password mapping_nc found.")
```    

### 8.4 Check drivers

```python
from nautobot.dcim.models import Platform
for platform in Platform.objects.all():
    print(f"Platform: {platform.name}")
    print(f"  Network Driver: {platform.network_driver}")
    print(f"  Network Driver Mappings: {platform.network_driver_mappings}")
    print("-" * 30)
```

