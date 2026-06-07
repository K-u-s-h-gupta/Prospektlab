# ProspektLab Mass Outreach

This folder is for acquisition outreach only. It is intentionally separate from the ProspektLab platform backend, which should stay focused on product auth email/SMS.

## Current Sender Status

The branded outreach sender domain is `notify.prospektlab.com`.

Do not run bulk outreach from `*.azurecomm.net` sender addresses. They are useful for setup tests, but they look automated and will damage trust for cold acquisition. The send runner refuses live sends from non-branded domains unless explicitly overridden.

## Sender Model

Use person-named senders on the verified ACS domain:

- `aryan@notify.prospektlab.com`, replies to `aryan@prospektlab.com`
- `kushargra@notify.prospektlab.com`, replies to `kushargra@prospektlab.com`
- `riya@notify.prospektlab.com`, replies to `aryan@prospektlab.com`
- `ananya@notify.prospektlab.com`, replies to `kushargra@prospektlab.com`
- `rohan@notify.prospektlab.com`, replies to `aryan@prospektlab.com`
- `aditya@notify.prospektlab.com`, replies to `kushargra@prospektlab.com`
- `neha@notify.prospektlab.com`, replies to `aryan@prospektlab.com`
- `ishaan@notify.prospektlab.com`, replies to `kushargra@prospektlab.com`
- `kavya@notify.prospektlab.com`, replies to `aryan@prospektlab.com`

Keep `auth@notify.prospektlab.com` only for product authentication. Do not reuse it for campaigns.

For early outreach, prefer `aryan` and `kushargra`. Use the other person-named senders only after the domain has clean pilot metrics.

## Message Structure

Every first-touch email should follow this structure:

1. Hook: a specific observation about the person, firm, market, content, portfolio workflow, or role.
2. Compliment/personalization: a real, grounded compliment that proves the message was written for them.
3. Platform intro: one short explanation of ProspektLab as an investment research workspace.
4. Natural CTA: ask them to try ProspektLab and give direct feedback.
5. Feedback group: include the WhatsApp invite link for people who choose to join.
6. Compliance footer: include unsubscribe text and physical mailing address before any real send.

WhatsApp group note: people cannot be silently added to a WhatsApp group by email. The compliant flow is to give them the invite link and let them join. The campaign template includes that link.

## Setup

Run this after adding DNS records for `notify.prospektlab.com`:

```powershell
powershell -ExecutionPolicy Bypass -File .\deployment\setup_acs_outreach.ps1 -WriteConfig
```

The script writes `outreach/config.local.json`, which is ignored by git because it contains the ACS connection string.

## Dry Run

Prepare leads in `outreach/leads.csv` using `outreach/leads.sample.csv` as the shape. Then preview without sending:

```powershell
.\.venv-finagent-311\Scripts\python.exe .\outreach\scripts\send_outreach_batch.py --config .\outreach\config.local.json --leads .\outreach\leads.csv --max-per-run 10
```

## Controlled Send

Only send after the branded domain is verified and every lead has real personalization:

```powershell
.\.venv-finagent-311\Scripts\python.exe .\outreach\scripts\send_outreach_batch.py --config .\outreach\config.local.json --leads .\outreach\leads.csv --max-per-run 25 --delay-seconds 90 --send
```

Start with 25-50/day, then ramp only if bounces, complaints, and replies stay healthy. For 10k recipients, request an ACS Email quota increase after the custom domain is verified and the pilot metrics are clean.
