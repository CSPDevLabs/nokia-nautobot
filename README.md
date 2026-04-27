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

