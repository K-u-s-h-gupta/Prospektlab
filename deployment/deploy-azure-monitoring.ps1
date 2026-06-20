# Deploys Azure monitoring + security + governance stack:
# - Log Analytics workspace
# - Workspace-based Application Insights
# - Microsoft Sentinel onboarding
# - Microsoft Purview account (optional)
# - Defender for Cloud paid plans (focused scope at subscription level)
# - Cost budget guardrails for focused resource group scope

param(
    [string]$ResourceGroup = "prospektlab-monitoring-rg",
    [string]$Location = "centralindia",
    [string]$WorkspaceName = "prospektlab-monitoring",
    [string]$AppInsightsName = "prospektlab-appinsights",
    [string]$PurviewAccountName = "prospektlab-purview",
    [string]$PurviewManagedResourceGroupName = "prospektlab-purview-managed",
    [int]$RetentionInDays = 90,
    [int]$DailyQuotaGb = 50,
    [int]$TargetMonthlyUsd = 100,
    [int]$HardCapMonthlyUsd = 120,
    [ValidateSet("focused", "all")]
    [string]$DefenderScopeMode = "focused",
    [bool]$PurviewEnableGovernance = $true,
    [bool]$PurviewEnableSecurity = $true,
    [ValidateSet("all_available", "app_db_only", "custom")]
    [string]$PurviewSourceMode = "all_available",
    [string[]]$DefenderPlans = @("VirtualMachines", "AppServices", "SqlServers", "StorageAccounts", "Containers", "KeyVaults"),
    [string]$BudgetName = "prospektlab-ops-budget",
    [string[]]$BudgetContactEmails = @(),
    [switch]$SkipDefender,
    [switch]$SkipBudget
)

$ErrorActionPreference = "Stop"

function Invoke-AzCli {
    param(
        [string[]]$Args,
        [switch]$AllowFailure
    )

    $output = & az @Args 2>&1
    $commandSucceeded = $?
    $exitCode = $LASTEXITCODE
    $outputText = ""

    if ($output) {
        $outputText = $output | Out-String
        $outputText | Write-Verbose
    }
    $reportedError = $outputText -match "(^|`n)\s*ERROR:"

    if (($reportedError -or -not $commandSucceeded -or $exitCode -ne 0) -and -not $AllowFailure) {
        throw ("Azure CLI command failed: az " + ($Args -join " "))
    }

    if ($reportedError -or -not $commandSucceeded -or $exitCode -ne 0) {
        return 1
    }
    return 0
}

function Ensure-MonitoringStackDirect {
    param(
        [string]$ResourceGroup,
        [string]$Location,
        [string]$WorkspaceName,
        [string]$AppInsightsName,
        [string]$PurviewAccountName,
        [string]$PurviewManagedResourceGroupName,
        [int]$RetentionInDays,
        [int]$DailyQuotaGb,
        [bool]$PurviewEnableGovernance,
        [bool]$PurviewEnableSecurity
    )

    Write-Warning "Using direct Azure CLI provisioning fallback (Bicep build/deploy unavailable)."

    Invoke-AzCli -Args @(
        "monitor", "log-analytics", "workspace", "create",
        "--resource-group", $ResourceGroup,
        "--workspace-name", $WorkspaceName,
        "--location", $Location,
        "--retention-time", "$RetentionInDays",
        "--sku", "PerGB2018"
    ) | Out-Null

    Invoke-AzCli -Args @(
        "monitor", "log-analytics", "workspace", "update",
        "--resource-group", $ResourceGroup,
        "--workspace-name", $WorkspaceName,
        "--quota", "$DailyQuotaGb"
    ) | Out-Null

    $workspaceId = az monitor log-analytics workspace show `
        --resource-group $ResourceGroup `
        --workspace-name $WorkspaceName `
        --query id -o tsv --only-show-errors
    if ([string]::IsNullOrWhiteSpace($workspaceId)) {
        throw "Could not resolve workspace resource ID for '$WorkspaceName'."
    }

    $appInsightsPayload = @{
        location = $Location
        kind = 'web'
        properties = @{
            Application_Type = 'web'
            WorkspaceResourceId = $workspaceId
            SamplingPercentage = 100
            RetentionInDays = $RetentionInDays
            publicNetworkAccessForIngestion = 'Enabled'
            publicNetworkAccessForQuery = 'Enabled'
            DisableIpMasking = $false
            DisableLocalAuth = $false
            ForceCustomerStorageForProfiler = $false
        }
    }
    $appInsightsPayloadPath = Join-Path $env:TEMP ("prospektlab-appinsights-" + [guid]::NewGuid().ToString() + ".json")
    Set-Content -LiteralPath $appInsightsPayloadPath -Value ($appInsightsPayload | ConvertTo-Json -Depth 8) -Encoding UTF8
    Invoke-AzCli -Args @(
        "resource", "create",
        "--resource-group", $ResourceGroup,
        "--name", $AppInsightsName,
        "--resource-type", "Microsoft.Insights/components",
        "--api-version", "2020-02-02",
        "--is-full-object",
        "--properties", "@$appInsightsPayloadPath"
    ) | Out-Null

    $subscriptionId = az account show --query id -o tsv --only-show-errors
    if ([string]::IsNullOrWhiteSpace($subscriptionId)) {
        throw "Could not resolve active subscription ID for Sentinel onboarding fallback."
    }
    $sentinelOnboardingId = "/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.OperationalInsights/workspaces/$WorkspaceName/providers/Microsoft.SecurityInsights/onboardingStates/default"
    Invoke-AzCli -Args @(
        "resource", "create",
        "--id", $sentinelOnboardingId,
        "--api-version", "2025-09-01",
        "--properties", "{}"
    ) | Out-Null

    if ($PurviewEnableGovernance -or $PurviewEnableSecurity) {
        $purviewPayload = @{
            location = $Location
            identity = @{
                type = 'SystemAssigned'
            }
            properties = @{
                managedResourceGroupName = $PurviewManagedResourceGroupName
                publicNetworkAccess = 'Enabled'
            }
        }
        $purviewPayloadPath = Join-Path $env:TEMP ("prospektlab-purview-" + [guid]::NewGuid().ToString() + ".json")
        Set-Content -LiteralPath $purviewPayloadPath -Value ($purviewPayload | ConvertTo-Json -Depth 8) -Encoding UTF8
        Invoke-AzCli -Args @(
            "resource", "create",
            "--resource-group", $ResourceGroup,
            "--name", $PurviewAccountName,
            "--resource-type", "Microsoft.Purview/accounts",
            "--api-version", "2021-12-01",
            "--is-full-object",
            "--properties", "@$purviewPayloadPath"
        ) | Out-Null
    }
}

try {
    Invoke-AzCli -Args @("account", "show", "--output", "none") | Out-Null
} catch {
    throw "Azure CLI is not signed in yet. Run: az login --use-device-code"
}

Write-Host "Registering required providers..." -ForegroundColor Cyan
$requiredNamespaces = @(
    "Microsoft.OperationsManagement",
    "Microsoft.OperationalInsights",
    "Microsoft.Insights",
    "Microsoft.SecurityInsights",
    "Microsoft.Security",
    "Microsoft.Purview",
    "Microsoft.Consumption"
)
foreach ($namespace in $requiredNamespaces) {
    Invoke-AzCli -Args @("provider", "register", "--namespace", $namespace) | Out-Null
}

foreach ($namespace in $requiredNamespaces) {
    $registered = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $state = ""
        try {
            $state = az provider show --namespace $namespace --query registrationState -o tsv --only-show-errors
        } catch {
            $state = ""
        }
        if ($state -eq "Registered") {
            $registered = $true
            break
        }
        Start-Sleep -Seconds 5
    }
    if (-not $registered) {
        throw "Provider namespace '$namespace' is not fully registered yet."
    }
}

Write-Host "Creating resource group if needed..." -ForegroundColor Cyan
Invoke-AzCli -Args @("group", "create", "--name", $ResourceGroup, "--location", $Location) | Out-Null

Write-Host "Building Bicep templates to JSON..." -ForegroundColor Cyan
$buildDir = Join-Path $env:TEMP "prospektlab-azure-build"
New-Item -ItemType Directory -Path $buildDir -Force | Out-Null
$rgTemplateFile = Join-Path $buildDir "azure-monitoring.json"
$subTemplateFile = Join-Path $buildDir "azure-security-subscription.json"
Remove-Item -LiteralPath $rgTemplateFile -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $subTemplateFile -ErrorAction SilentlyContinue
$rgBuildExit = Invoke-AzCli -AllowFailure -Args @("bicep", "build", "--file", "deployment/azure-monitoring.bicep", "--outfile", $rgTemplateFile)
$subBuildExit = Invoke-AzCli -AllowFailure -Args @("bicep", "build", "--file", "deployment/azure-security-subscription.bicep", "--outfile", $subTemplateFile)
$rgTemplateReady = ($rgBuildExit -eq 0) -and (Test-Path -LiteralPath $rgTemplateFile)
$subTemplateReady = ($subBuildExit -eq 0) -and (Test-Path -LiteralPath $subTemplateFile)

if ($rgTemplateReady) {
    Write-Host "Deploying resource-group scoped monitoring/security/governance resources..." -ForegroundColor Cyan
    $rgDeployExit = Invoke-AzCli -AllowFailure -Args @(
        "deployment", "group", "create",
        "--name", "azure-monitoring-v2",
        "--resource-group", $ResourceGroup,
        "--template-file", $rgTemplateFile,
        "--parameters",
        "location=$Location",
        "workspaceName=$WorkspaceName",
        "appInsightsName=$AppInsightsName",
        "purviewAccountName=$PurviewAccountName",
        "purviewManagedResourceGroupName=$PurviewManagedResourceGroupName",
        "retentionInDays=$RetentionInDays",
        "dailyQuotaGb=$DailyQuotaGb",
        "targetMonthlyUsd=$TargetMonthlyUsd",
        "hardCapMonthlyUsd=$HardCapMonthlyUsd",
        "defenderScopeMode=$DefenderScopeMode",
        "purviewEnableGovernance=$PurviewEnableGovernance",
        "purviewEnableSecurity=$PurviewEnableSecurity",
        "purviewSourceMode=$PurviewSourceMode"
    )

    if ($rgDeployExit -ne 0) {
        Ensure-MonitoringStackDirect `
            -ResourceGroup $ResourceGroup `
            -Location $Location `
            -WorkspaceName $WorkspaceName `
            -AppInsightsName $AppInsightsName `
            -PurviewAccountName $PurviewAccountName `
            -PurviewManagedResourceGroupName $PurviewManagedResourceGroupName `
            -RetentionInDays $RetentionInDays `
            -DailyQuotaGb $DailyQuotaGb `
            -PurviewEnableGovernance $PurviewEnableGovernance `
            -PurviewEnableSecurity $PurviewEnableSecurity
    }
} else {
    Ensure-MonitoringStackDirect `
        -ResourceGroup $ResourceGroup `
        -Location $Location `
        -WorkspaceName $WorkspaceName `
        -AppInsightsName $AppInsightsName `
        -PurviewAccountName $PurviewAccountName `
        -PurviewManagedResourceGroupName $PurviewManagedResourceGroupName `
        -RetentionInDays $RetentionInDays `
        -DailyQuotaGb $DailyQuotaGb `
        -PurviewEnableGovernance $PurviewEnableGovernance `
        -PurviewEnableSecurity $PurviewEnableSecurity
}

if (-not $SkipDefender) {
    Write-Host "Deploying subscription-scoped Defender plans..." -ForegroundColor Cyan
    $defenderDeploymentExit = 1
    if ($subTemplateReady) {
        $plansJson = ($DefenderPlans | ConvertTo-Json -Compress)
        $defenderDeploymentExit = Invoke-AzCli -AllowFailure -Args @(
            "deployment", "sub", "create",
            "--location", $Location,
            "--name", "prospektlab-security-sub",
            "--template-file", $subTemplateFile,
            "--parameters",
            "defenderScopeMode=$DefenderScopeMode",
            "enableDefender=true",
            "defenderPlans=$plansJson"
        )
    }

    if ($defenderDeploymentExit -ne 0) {
        Write-Warning "Subscription-scope deployment failed. Falling back to direct Defender pricing commands."
        foreach ($plan in $DefenderPlans) {
            Invoke-AzCli -Args @("security", "pricing", "create", "-n", $plan, "--tier", "standard") | Out-Null
        }
    }
}

if (-not $SkipBudget) {
    Write-Host "Creating resource-group budget guardrails..." -ForegroundColor Cyan
    # Use explicit UTC timestamps so time-zone conversion never shifts to the previous day.
    $startDate = ([DateTime]::UtcNow).ToString("yyyy-MM-01T00:00:00Z")
    $endDate = ([DateTime]::UtcNow.AddYears(1)).ToString("yyyy-MM-01T00:00:00Z")

    $baseBudgetArgs = @(
        "consumption", "budget", "create-with-rg",
        "--resource-group", $ResourceGroup,
        "--budget-name", $BudgetName,
        "--amount", "$TargetMonthlyUsd",
        "--category", "Cost",
        "--time-grain", "Monthly",
        "--time-period", "start-date=$startDate", "end-date=$endDate"
    )

    $emailList = @(
        $BudgetContactEmails |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -ne "" }
    )

    if ($emailList.Count -eq 0) {
        try {
            $signedInUser = az account show --query "user.name" -o tsv --only-show-errors
            if ($signedInUser -and $signedInUser.Contains("@")) {
                $emailList = @($signedInUser.Trim())
                Write-Host "BudgetContactEmails not provided. Using signed-in account email '$signedInUser' for budget alerts." -ForegroundColor Yellow
            }
        } catch {
            # Leave email list empty and proceed with no notifications.
        }
    }

    if ($emailList.Count -eq 0) {
        Write-Warning "BudgetContactEmails was empty. Creating budget without threshold notifications. Re-run with at least one email to enable 50/75/90/100 alerts."
        Invoke-AzCli -Args $baseBudgetArgs | Out-Null
    } else {
        $notificationPayload = @{
            actual50 = @{
                enabled = $true
                operator = "GreaterThanOrEqualTo"
                threshold = 50
                contactEmails = $emailList
                contactRoles = @("Owner")
            }
            actual75 = @{
                enabled = $true
                operator = "GreaterThanOrEqualTo"
                threshold = 75
                contactEmails = $emailList
                contactRoles = @("Owner")
            }
            actual90 = @{
                enabled = $true
                operator = "GreaterThanOrEqualTo"
                threshold = 90
                contactEmails = $emailList
                contactRoles = @("Owner")
            }
            actual100 = @{
                enabled = $true
                operator = "GreaterThanOrEqualTo"
                threshold = 100
                contactEmails = $emailList
                contactRoles = @("Owner")
            }
        }

        $notificationsPath = Join-Path $env:TEMP ("prospektlab-budget-notifications-" + [guid]::NewGuid().ToString() + ".json")
        Set-Content -LiteralPath $notificationsPath -Value ($notificationPayload | ConvertTo-Json -Depth 8) -Encoding UTF8
        Invoke-AzCli -Args ($baseBudgetArgs + @("--notifications", "@$notificationsPath")) | Out-Null
    }
}

Write-Host "Deployment complete." -ForegroundColor Green
Write-Host "Run deployment\\azure-cost-guardrail.ps1 for hard-cap throttling actions when needed." -ForegroundColor Yellow
Write-Host "Review deployment\\purview-sources.sample.json and register data sources in Purview using your real credentials." -ForegroundColor Yellow
