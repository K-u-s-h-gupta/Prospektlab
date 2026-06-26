# Deliverability Checklist

Use this before any campaign larger than a tiny pilot.

## Domain

- `notify.prospektlab.com` is verified in ACS for Domain, SPF, DKIM, and DKIM2.
- DMARC is present for the outreach subdomain or inherited from the parent domain.
- First live campaign uses only `aryan@notify.prospektlab.com` and `kushargra@notify.prospektlab.com`.
- No acquisition campaign uses `*.azurecomm.net`.

## List Quality

- Every row has a real source, a real hook, and a real compliment.
- No scraped personal emails unless there is a clear lawful basis and relevance.
- Remove role accounts unless the message is clearly relevant to that role.
- Suppress bounced, unsubscribed, complained, replied-negative, and already-contacted addresses.

### Enhanced Filters (v2 - June 2026)

The batch script now enforces these additional filters automatically:

- **MX verification**: Emails to domains without valid MX records are rejected pre-send. Use `--skip-mx-verify` only for testing.
- **Stricter confidence gate**: "verified" or "valid" status must also have `email_confidence >= 0.7` (previously status alone was enough).
- **Disposable domain blocklist**: Known temporary/throwaway email services are auto-rejected.
- **Auto-suppression of failures**: Addresses that previously bounced with permanent errors are automatically excluded from future batches.

Target: **<2% send failure rate** (script halts if exceeded).

## Copy

- Subject is direct and human, not clickbait.
- First two lines prove why this person received the email.
- CTA asks for a trial and feedback, not a hard sale.
- WhatsApp group appears as an optional feedback invite after the product CTA.
- Unsubscribe language and physical mailing address are present.

## Throttle

- Start at 25-50/day total on the branded domain.
- Keep at least 60-120 seconds between sends during pilots.
- Ramp only after checking bounce, complaint, reply, and signup quality.
- Request Azure quota increase before planning 10k-scale sends.

## Stop Conditions

- Bounce rate is rising.
- More than a small handful of recipients complain or ask why they were contacted.
- Reply quality suggests the audience is wrong.
- The branded domain shows authentication or reputation warnings.
