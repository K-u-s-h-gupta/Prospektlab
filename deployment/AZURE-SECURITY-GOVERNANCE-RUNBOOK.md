# Azure Security + Governance Runbook

This runbook covers the focused rollout for:
- Azure Monitor + Application Insights + Sentinel
- Defender for Cloud (focused plans)
- Microsoft Purview (governance and security lanes)
- Budget + hard-cap guardrails

## 1) Deploy

Run the deployment script:

```powershell
.\deployment\deploy-azure-monitoring.ps1 `
  -ResourceGroup prospektlab-monitoring-rg `
  -Location centralindia `
  -WorkspaceName prospektlab-monitoring `
  -AppInsightsName prospektlab-appinsights `
  -PurviewAccountName prospektlab-purview `
  -TargetMonthlyUsd 100 `
  -HardCapMonthlyUsd 120 `
  -DefenderScopeMode focused `
  -PurviewEnableGovernance $true `
  -PurviewEnableSecurity $true `
  -PurviewSourceMode all_available
```

Optional:
- `-SkipDefender` to skip subscription-level Defender rollout.
- `-SkipBudget` to skip budget creation in environments with custom cost tooling.
- The script auto-falls back to direct Azure CLI provisioning when local `az bicep build` is unavailable.

## 2) Verify in Portal

Resource Group:
- Confirm workspace, App Insights, Sentinel onboarding, and Purview account are present.

Sentinel:
- Open the workspace in Sentinel and verify onboarding state is active.

Defender:
- Confirm selected plans are enabled in Defender for Cloud and recommendations are visible.

Purview:
- Open Purview account and verify governance/security features are available.
- Register real data sources using your credentials and network reachability.
- Use `deployment/purview-sources.sample.json` as the source inventory template.

## 3) Cost Controls

Budget:
- Ensure budget exists at focused resource-group scope with target amount.
- Validate notifications at 50/75/90/100 thresholds.

Hard Cap Guardrail:
- Run guardrail when spend approaches hard cap.

```powershell
.\deployment\azure-cost-guardrail.ps1 `
  -ResourceGroup prospektlab-monitoring-rg `
  -WorkspaceName prospektlab-monitoring `
  -HardCapMonthlyUsd 120 `
  -CurrentMonthSpendUsd 121
```

This lowers Log Analytics daily quota to reduce optional high-volume ingestion.

## 4) Rollback Toggles

- Defender rollback:
  - Re-run deployment with `-SkipDefender` and manually downgrade specific Defender plans if required.
- Purview rollback:
  - Re-run with `-PurviewEnableGovernance $false -PurviewEnableSecurity $false`.
  - Keep account for audit history or remove after export if policy allows.
- Budget rollback:
  - Remove or update budget with `az consumption budget delete` / `update`.
- Quota rollback:
  - Raise workspace quota via:
  - `az monitor log-analytics workspace update -g <rg> -n <ws> --quota -1`

## 5) Weekly Operating Cadence

- Daily:
  - Review spend trend against `$100` target and `$120` hard cap.
- Weekly:
  - Tune telemetry depth, Defender plan scope, and Purview scan coverage.
  - Keep security coverage intact; adjust only optional high-volume paths.
