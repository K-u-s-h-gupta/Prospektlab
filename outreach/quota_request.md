# Azure ACS Email Quota Request Draft

Quota type: Azure Communication Services Email: Sending Limits

Subscription: `67f5fdc5-9822-4705-b758-9e9dc59af6f6`

Communication Services resource: `prospektlab-comms`

Email Communication Services resource: `prospektlab-email`

Email domain resource: `notify.prospektlab.com`

Requested limit:

- Initial: 10,000 recipients/day
- Hourly cap: 1,000/hour
- Sender pacing: controlled queue with 60-120 seconds between early sends and gradual ramp

Use case:

ProspektLab is running personalized B2B user acquisition outreach to invite relevant investors, analysts, and finance operators to try the ProspektLab research platform and provide product feedback. Campaigns are personalized per recipient using lead-specific hooks and compliments. Recipients can unsubscribe, reply directly to founder inboxes, or join an optional WhatsApp feedback group after signup.

Controls in place:

- Custom ACS domain: `notify.prospektlab.com`
- Person-named sender identities: `aryan@notify.prospektlab.com`, `kushargra@notify.prospektlab.com`
- Reply-To routes to real Microsoft 365 founder inboxes
- Suppression list for unsubscribes, bounces, complaints, and negative replies
- CSV sent log with timestamp, sender, subject, message ID, and source URL
- Live send guard blocks Azure-managed `*.azurecomm.net` campaign senders
- Required unsubscribe URL and physical mailing address before live sends
- Batch-size and delay controls in sender script

Expected content:

Short personalized first-touch emails with this structure: specific hook, compliment/personalization, ProspektLab intro, natural feedback CTA, optional WhatsApp feedback group invite, unsubscribe footer.
