
```bash
export NAUTOBOT_TOKEN=$(kubectl get secret --namespace default nautobot-env -o jsonpath="{.data.NAUTOBOT_SUPERUSER_API_TOKEN}" | base64 --decode)
python nautobot_population.py \
    ../../nok-clabs/nok-dia/topo.clab.yaml \
    --nautobot-url "https://nautobot-host:8443" \
    --nautobot-token $NAUTOBOT_TOKEN \
    --site-name "nok-dia" \
    --platform-name "SROS" \
    --no-verify-ssl    
```

```bash
export NAUTOBOT_TOKEN=$(kubectl get secret --namespace default nautobot-env -o jsonpath="{.data.NAUTOBOT_SUPERUSER_API_TOKEN}" | base64 --decode)
python nautobot_population.py --nautobot-url "https://nautobot-host:8443" \
    --nautobot-token $NAUTOBOT_TOKEN \
    --initial-data-file nokia-sros-data.json \
    --no-verify-ssl 
```