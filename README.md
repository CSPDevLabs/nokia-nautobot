
```bash
helm repo add nautobot https://nautobot.github.io/helm-charts/
```

```bash
helm show values nautobot/nautobot > values-default.yaml
```

```bash
kubectl apply -f postg-redis.yaml
```


```bash
helm install nautobot nautobot/nautobot -f values-ext-db.yaml
```

1. Get the Nautobot URL:

  echo "Nautobot URL: http://127.0.0.1:8080/"
  kubectl port-forward --namespace default svc/nautobot-default 8080:80

2. Get your Nautobot login admin credentials by running:

  echo Username: admin
  echo Password: $(kubectl get secret --namespace default nautobot-env -o jsonpath="{.data.NAUTOBOT_SUPERUSER_PASSWORD}" | base64 --decode)
  echo api-token: $(kubectl get secret --namespace default nautobot-env -o jsonpath="{.data.NAUTOBOT_SUPERUSER_API_TOKEN}" | base64 --decode)

Make sure you take note of your Nautobot `NAUTOBOT_SECRET_KEY` by running:

  echo Secret Key: $(kubectl get secret --namespace default nautobot-env -o jsonpath="{.data.NAUTOBOT_SECRET_KEY}" | base64 --decode)# nokia-nautobot
