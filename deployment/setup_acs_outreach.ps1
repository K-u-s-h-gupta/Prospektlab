param(
    [string]$ResourceGroup = "rg-PROSPEKTLAB",
    [string]$CommunicationServiceName = "prospektlab-comms",
    [string]$EmailServiceName = "prospektlab-email",
    [string]$BrandedDomain = "notify.prospektlab.com",
    [string[]]$SenderUsernames = @("aryan", "kushargra", "riya", "ananya", "rohan", "aditya", "neha", "ishaan", "kavya"),
    [switch]$WriteConfig
)

$ErrorActionPreference = "Stop"

function Get-DisplayNameForSender {
    param([Parameter(Mandatory = $true)][string]$SenderUsername)

    switch ($SenderUsername.Trim().ToLowerInvariant()) {
        "aryan" { return "Aryan | ProspektLab" }
        "kushargra" { return "Kushargra | ProspektLab" }
        "riya" { return "Riya | ProspektLab" }
        "ananya" { return "Ananya | ProspektLab" }
        "rohan" { return "Rohan | ProspektLab" }
        "aditya" { return "Aditya | ProspektLab" }
        "neha" { return "Neha | ProspektLab" }
        "ishaan" { return "Ishaan | ProspektLab" }
        "kavya" { return "Kavya | ProspektLab" }
        default {
            $title = (Get-Culture).TextInfo.ToTitleCase($SenderUsername.Replace(".", " ").Replace("_", " ").Replace("-", " "))
            return "$title | ProspektLab"
        }
    }
}

function Test-DomainFullyVerified {
    param($DomainResource)

    if ($null -eq $DomainResource) {
        return $false
    }

    foreach ($entryName in @("Domain", "SPF", "DKIM", "DKIM2")) {
        $state = $DomainResource.verificationStates.$entryName
        if ($null -eq $state -or $state.status -ne "Verified") {
            return $false
        }
    }

    return $true
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$comm = az communication show -g $ResourceGroup -n $CommunicationServiceName -o json | ConvertFrom-Json
$keys = az communication list-key -g $ResourceGroup -n $CommunicationServiceName -o json | ConvertFrom-Json
$domain = az communication email domain show `
    --resource-group $ResourceGroup `
    --email-service-name $EmailServiceName `
    --domain-name $BrandedDomain `
    -o json | ConvertFrom-Json

foreach ($sender in $SenderUsernames) {
    $normalized = $sender.Trim().ToLowerInvariant()
    $displayName = Get-DisplayNameForSender -SenderUsername $normalized
    az communication email domain sender-username create `
        --domain-name $BrandedDomain `
        --email-service-name $EmailServiceName `
        --resource-group $ResourceGroup `
        --sender-username $normalized `
        --username $normalized `
        --display-name $displayName `
        -o none | Out-Null
}

$domainReady = Test-DomainFullyVerified -DomainResource $domain

Write-Host ""
Write-Host "ACS Communication Service: $($comm.hostName)"
Write-Host "Outreach domain: $BrandedDomain"
Write-Host "Domain ready for branded sending: $domainReady"
Write-Host ""
Write-Host "Sender addresses:"
foreach ($sender in $SenderUsernames) {
    Write-Host ("- {0}@{1}" -f $sender.Trim().ToLowerInvariant(), $BrandedDomain)
}

if (-not $domainReady) {
    Write-Host ""
    Write-Host "DNS records still required for ${BrandedDomain}:"
    foreach ($entryName in @("Domain", "SPF", "DKIM", "DKIM2")) {
        $record = $domain.verificationRecords.$entryName
        if ($null -ne $record) {
            Write-Host ("- {0}: {1} {2} {3}" -f $entryName, $record.type, $record.name, $record.value)
        }
    }

    Write-Host ""
    Write-Host "Current verification states:"
    foreach ($entryName in @("Domain", "SPF", "DKIM", "DKIM2", "DMARC")) {
        $state = $domain.verificationStates.$entryName
        if ($null -ne $state) {
            Write-Host ("- {0}: {1}" -f $entryName, $state.status)
        }
    }
}

if ($WriteConfig) {
    $configPath = Join-Path $repoRoot "outreach\config.local.json"
    $configDir = Split-Path -Parent $configPath
    if (-not (Test-Path -LiteralPath $configDir)) {
        New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    }

    $config = [ordered]@{
        azure = [ordered]@{
            connection_string = $keys.primaryConnectionString
            domain = $BrandedDomain
            require_custom_domain = $true
            allow_managed_domain = $false
            verified = $domainReady
        }
        campaign = [ordered]@{
            signup_url = "https://prospektlab.com/signup"
            utm_source = "outreach"
            utm_medium = "email"
            utm_campaign = "research_workflow_outreach"
            whatsapp_group_url = "https://chat.whatsapp.com/Bpo5Bt5tVveGYGEVawkcUu"
            unsubscribe_url = "https://prospektlab.com/unsubscribe"
            physical_address = ""
        }
        suppression_sync = [ordered]@{
            supabase_url = ""
            supabase_key = ""
        }
        senders = @(
            [ordered]@{
                key = "aryan"
                name = "Aryan"
                email = "aryan@$BrandedDomain"
                reply_to = "aryan@prospektlab.com"
            },
            [ordered]@{
                key = "kushargra"
                name = "Kushargra"
                email = "kushargra@$BrandedDomain"
                reply_to = "kushargra@prospektlab.com"
            },
            [ordered]@{
                key = "riya"
                name = "Riya"
                email = "riya@$BrandedDomain"
                reply_to = "aryan@prospektlab.com"
            },
            [ordered]@{
                key = "ananya"
                name = "Ananya"
                email = "ananya@$BrandedDomain"
                reply_to = "kushargra@prospektlab.com"
            },
            [ordered]@{
                key = "rohan"
                name = "Rohan"
                email = "rohan@$BrandedDomain"
                reply_to = "aryan@prospektlab.com"
            },
            [ordered]@{
                key = "aditya"
                name = "Aditya"
                email = "aditya@$BrandedDomain"
                reply_to = "kushargra@prospektlab.com"
            },
            [ordered]@{
                key = "neha"
                name = "Neha"
                email = "neha@$BrandedDomain"
                reply_to = "aryan@prospektlab.com"
            },
            [ordered]@{
                key = "ishaan"
                name = "Ishaan"
                email = "ishaan@$BrandedDomain"
                reply_to = "kushargra@prospektlab.com"
            },
            [ordered]@{
                key = "kavya"
                name = "Kavya"
                email = "kavya@$BrandedDomain"
                reply_to = "aryan@prospektlab.com"
            }
        )
    }

    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 8), $utf8NoBom)
    Write-Host ""
    Write-Host "Wrote $configPath"
    if (-not $domainReady) {
        Write-Host "Live sends will still be blocked by the outreach runner until DNS verification is complete."
    }
}
