```bash
python populate_nautobot_from_clab_sros_only.py \
    ../../nok-clabs/nok-dia/topo.clab.yaml \
    --nautobot-url "https://nautobot-host:8443" \
    --nautobot-token $NAUTOBOT_TOKEN \
    --sros-username "admin" \
    --sros-password "NokiaSros1!" \
    --site-name "nok-dia" \
    --platform-name "NokiaSROS" \
    --no-verify-ssl    
```