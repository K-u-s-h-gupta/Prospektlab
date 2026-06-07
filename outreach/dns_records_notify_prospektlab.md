# DNS Records For notify.prospektlab.com

Add these in Spaceship DNS, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\deployment\setup_acs_outreach.ps1 -WriteConfig
```

## Records

- `TXT` host `notify.prospektlab.com` value `ms-domain-verification=08d45b68-3004-4db4-9ad9-6fb318e9c819`
- `TXT` host `notify.prospektlab.com` value `v=spf1 include:spf.protection.outlook.com -all`
- `CNAME` host `selector1-azurecomm-prod-net._domainkey` value `selector1-azurecomm-prod-net._domainkey.azurecomm.net`
- `CNAME` host `selector2-azurecomm-prod-net._domainkey` value `selector2-azurecomm-prod-net._domainkey.azurecomm.net`

Azure currently marks Domain, SPF, DKIM, DKIM2, and DMARC as `NotStarted` for this domain. The outreach sender refuses live sends until the generated config says the domain is verified.
