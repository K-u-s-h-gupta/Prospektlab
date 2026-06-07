# Microsoft 365 Domain Status

`prospektlab.com` is now added to the Microsoft 365 tenant, but it is not verified yet.

Current tenant observations:

- Tenant display name: `Prospektlab`
- Tenant primary domain: `ar2108925gmail.onmicrosoft.com`
- `prospektlab.com` added in Entra as an unverified custom domain
- Current subscribed SKUs: none

## Verification Records

Microsoft 365 currently expects these records for this tenant:

- `TXT` host `prospektlab.com` value `MS=ms93787248`
- Optional verification `MX` host `prospektlab.com` value `ms93787248.msv1.invalid` priority `32767`

Public DNS currently shows a different Microsoft verification TXT:

- `TXT` host `prospektlab.com` value `MS=ms54506566`

That mismatch is why this tenant still cannot verify `prospektlab.com`.

The TXT record is the important one for domain proof. The `.invalid` MX record is for verification flow only and should not replace your real mail routing unless you intentionally move inbound mail to Microsoft 365 later.

## Practical Meaning

Right now Microsoft 365 is not ready to create normal new `@prospektlab.com` mailboxes for outreach because:

- the custom domain is not verified yet
- the tenant currently shows no subscribed Exchange/Microsoft 365 SKUs

So the working split remains:

- ACS Email on `notify.prospektlab.com` for outbound outreach
- Microsoft 365 later, once verified/licensed, for cleaner shared inboxes or aliases if you want them
