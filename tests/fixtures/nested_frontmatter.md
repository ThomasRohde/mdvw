---
title: Deployment Runbook
version: 3.1
environment:
  name: production
  region: eu-west-1
  cluster: k8s-prod-07
dependencies:
  postgres:
    version: "16.2"
    host: db-prod.internal
  redis:
    version: "7.2"
    host: cache-prod.internal
flags:
  feature_new_checkout: true
  feature_dark_mode: false
  maintenance_window: null
rollback_contacts:
  - name: Thomas
    role: oncall
    phone: "+45 1234 5678"
  - name: Jane
    role: backup
    phone: "+1 555 0199"
---

# Deployment Runbook — v3.1

## Pre-flight Checklist

- [ ] All CI checks green
- [ ] Staging smoke tests passed
- [ ] Database migrations reviewed
- [ ] Feature flags configured

## Steps

1. Scale down canary deployment
2. Apply database migrations
3. Roll out new image to 10 % of pods
4. Monitor error rate for 15 minutes
5. Proceed to full rollout

## Rollback

If error rate exceeds 0.5 %, immediately:

```bash
kubectl rollout undo deployment/checkout -n production
```

Then page the oncall contact listed in the frontmatter above.
