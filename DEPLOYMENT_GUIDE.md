# Deployment & Testing Guide: Outreach Failure Rate Reduction (v2)

## Quick Summary

**Goal:** Reduce bounce/failure rate from ~11% to <2%

**Changes:**
- ✅ Added MX record verification (pre-send DNS check)
- ✅ Stricter email confidence gating (≥0.7 floor)
- ✅ Disposable domain blocklist (20+ services)
- ✅ Auto-suppression of permanently failed addresses
- ✅ UTM attribution tracking in frontend telemetry
- ✅ Added `dnspython` to requirements

---

## Deployment Steps

### Step 1: Update Dependencies

The `outreach/requirements.azure.txt` already includes `dnspython>=2.4.0,<3.0.0`.

**Install locally (optional, for testing):**
```bash
pip install --upgrade dnspython>=2.4.0
```

### Step 2: Verify Docker Build

The outreach Docker image will automatically install the new dependency:

```bash
# From the repo root:
docker build -f deployment/Dockerfile.azure -t prospektlab-outreach:v2 .
```

### Step 3: Update Azure Container App Job

If using Azure Container Apps:

```powershell
# Scale back to 0 to redeploy with new image
az containerapp job delete --name ca-outreach-batch --resource-group rg-PROSPEKTLAB

# Redeploy with new image (or update the image reference in your job definition)
az containerapp job create --resource-group rg-PROSPEKTLAB \
  --name ca-outreach-batch \
  --image prospektlab-outreach:v2 \
  --container-command "python" \
  --container-args "/app/outreach/scripts/run_azure_job.py" \
  # ... rest of your config
```

---

## Testing

### Test 1: Dry Run (No Emails Sent)

```bash
cd C:\Users\dev\Downloads\Prospektlab

# Dry run: preview batch without sending
python outreach/scripts/run_supabase_outreach_batch.py \
  --config outreach/config.local.json \
  --max-send 10 \
  --delay-seconds 0 \
  --min-email-confidence 0.85

# Output should show:
# - Total contacts processed
# - MX verification rejected X contacts (domain has no mail server)
# - Eligible leads after all filters
# - 10 DRY RUN previews
```

**Expected output snapshot:**
```
MX verification enabled — domains without mail servers will be rejected
Auto-suppressing X previously permanently-failed addresses
Supabase contacts=32662 india_strict=12000 ... eligible=2400 ...
MX verification rejected 150 contacts (domain has no mail server)
DRY RUN -> user1@company.com
...
Done: 10 previewed, 0 failed sends (0.00%), 0 skipped.
```

### Test 2: Live Send - Small Batch

```bash
# Live send: send 5 emails with MX verification enabled (default)
python outreach/scripts/run_supabase_outreach_batch.py \
  --config outreach/config.local.json \
  --max-send 5 \
  --delay-seconds 30 \
  --min-email-confidence 0.85 \
  --send

# Output should show:
# - SENT X: email@company.com via sender@notify.prospektlab.com
# - Failure rate should be 0/5 (0.00%)
```

**Expected output snapshot:**
```
Supabase contacts=32662 ... eligible=2400 ...
Campaign id=<uuid>
SENT 1: finance-head@company.com via aryan@notify.prospektlab.com (msg-id-123)
SENT 2: analyst@firm.com via kushargra@notify.prospektlab.com (msg-id-124)
...
Done: 5 sent, 0 failed sends (0.00%), 0 skipped.
```

### Test 3: Skip MX Verification (Regression Test)

```bash
# Compare: disable MX verification to see the difference
python outreach/scripts/run_supabase_outreach_batch.py \
  --config outreach/config.local.json \
  --max-send 10 \
  --delay-seconds 0 \
  --skip-mx-verify

# Output should show:
# - More eligible leads (since MX check is skipped)
# - No "MX verification rejected" line
```

---

## Expected Behavior Changes

### Before (Old Code)
- 2,413 emails sent / 2,529 total = 95.4% sent
- 116 failed = 4.6% message failure
- **But** some failures were preventable (bad domain, low confidence, etc.)

### After (New Code)
- ~1,900-2,100 emails sent (more filtered)
- Estimated 20-50 failed = ~1-2% failure rate
- **Fewer sent**, but **much healthier list**

### Monitoring in Supabase

Check the impact with this SQL:

```sql
-- Message failure rate trend
SELECT 
  DATE_TRUNC('day', sent_at) as day,
  COUNT(*) as total_sent,
  COUNTIF(status = 'failed') as failed,
  ROUND(100.0 * COUNTIF(status = 'failed') / COUNT(*), 2) as failure_rate
FROM outreach_messages
WHERE sent_at > NOW() - INTERVAL '30 days'
  AND owner_email = 'aryan@prospektlab.com'
GROUP BY day
ORDER BY day DESC;
```

---

## Monitoring in Control Tower

### Query 1: Outreach Email Metrics

```kusto
customEvents
| where name in ("outreach_batch_completed", "email_sent", "email_failed")
| summarize 
    sent_count = dcountif(tostring(customDimensions.message_id), name == "email_sent"),
    failed_count = dcountif(tostring(customDimensions.message_id), name == "email_failed")
  by bin(timestamp, 1d)
| project timestamp, sent_count, failed_count, 
    failure_rate = 100.0 * failed_count / (sent_count + failed_count)
| order by timestamp desc
```

### Query 2: Outreach → App Attribution

```kusto
customEvents
| where name in ("app_initialized", "signup_completed")
| where customDimensions.utm_source == "outreach"
| summarize 
    initializers = dcountif(tostring(customDimensions.session_id), name == "app_initialized"),
    signups = dcountif(tostring(customDimensions.session_id), name == "signup_completed")
  by bin(timestamp, 1d), tostring(customDimensions.utm_campaign)
| project timestamp, utm_campaign = column_name, initializers, signups
| order by timestamp desc
```

### Query 3: MX Filtering Impact

```kusto
pageViews
| where url contains "outreach" or url contains "utm_source=outreach"
| summarize page_views = count() by bin(timestamp, 1d)
| order by timestamp desc
```

---

## Rollback

If you need to revert:

1. **Revert code changes:**
   ```bash
   git checkout outreach/scripts/run_supabase_outreach_batch.py
   git checkout outreach/requirements.azure.txt
   git checkout Frontend/src/telemetry.ts
   ```

2. **Rebuild and redeploy Docker image:**
   ```bash
   docker build -f deployment/Dockerfile.azure -t prospektlab-outreach:v1 .
   ```

3. **Redeploy Azure Container App with v1 image**

---

## Files Modified

- ✅ `outreach/scripts/run_supabase_outreach_batch.py` — Added MX verification, auto-suppression, stricter confidence
- ✅ `outreach/requirements.azure.txt` — Added `dnspython>=2.4.0`
- ✅ `outreach/deliverability_checklist.md` — Documented new filters
- ✅ `Frontend/src/telemetry.ts` — Added UTM attribution tracking
- ✅ `outreach/scripts/test_mx_verification.py` — Optional test script (created)

---

## Support

If MX verification fails or times out:

1. **Disable for this run only:**
   ```bash
   python outreach/scripts/run_supabase_outreach_batch.py --skip-mx-verify --send
   ```

2. **Check DNS resolution:**
   ```bash
   nslookup gmail.com
   # Should return A/MX records
   ```

3. **Verify dnspython install:**
   ```bash
   python -c "import dns.resolver; print(dns.resolver.resolve('gmail.com', 'MX'))"
   ```

---

## Next Steps

1. ✅ Run **Test 1** (dry run) to verify the code works
2. ✅ Run **Test 2** (live send 5 emails) to verify sending still works
3. ✅ Deploy to Azure Container Apps
4. ✅ Monitor first week of batches for MX rejection counts
5. ✅ Check Control Tower for `utm_source=outreach` traffic
6. ✅ Gradually increase batch size (25 → 50 → 100) as confidence in failure rate grows
