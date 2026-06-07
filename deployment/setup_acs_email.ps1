param(
    [string]$ResourceGroup = "rg-PROSPEKTLAB",
    [string]$CommunicationServiceName = "prospektlab-comms",
    [string]$EmailServiceName = "prospektlab-email",
    [string]$BrandedDomain = "notify.prospektlab.com",
    [string]$SenderUsername = "auth",
    [switch]$PreferBrandedDomain,
    [switch]$WriteToFinagentEnv
)

$ErrorActionPreference = "Stop"

function Set-EnvFileValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        $lines = @(Get-Content -LiteralPath $Path)
    }
    $lines = @($lines)

    $updated = $false
    $escapedName = [regex]::Escape($Name)
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^${escapedName}=") {
            $lines[$i] = "$Name=$Value"
            $updated = $true
        }
    }

    if (-not $updated) {
        if ($lines.Count -gt 0 -and $lines[-1] -ne "") {
            $lines += ""
        }
        $lines += "$Name=$Value"
    }

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllLines($Path, $lines, $utf8NoBom)
}

function Get-DisplayNameForSender {
    param(
        [Parameter(Mandatory = $true)][string]$SenderUsername
    )

    $normalized = $SenderUsername.Trim().ToLowerInvariant()
    switch ($normalized) {
        "auth" { return "ProspektLab Auth" }
        default {
            $title = (Get-Culture).TextInfo.ToTitleCase($normalized.Replace(".", " ").Replace("_", " ").Replace("-", " "))
            return "$title | ProspektLab"
        }
    }
}

function Ensure-SenderUsername {
    param(
        [Parameter(Mandatory = $true)][string]$DomainName,
        [Parameter(Mandatory = $true)][string]$SenderUsername
    )

    $displayName = Get-DisplayNameForSender -SenderUsername $SenderUsername
    az communication email domain sender-username create `
        --domain-name $DomainName `
        --email-service-name $EmailServiceName `
        --resource-group $ResourceGroup `
        --sender-username $SenderUsername `
        --username $SenderUsername `
        --display-name $displayName `
        -o none | Out-Null
}

function Test-DomainFullyVerified {
    param(
        $DomainResource
    )

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
$phoneNumbers = az communication phonenumber list --connection-string $keys.primaryConnectionString -o json | ConvertFrom-Json
$domains = az communication email domain list -g $ResourceGroup --email-service-name $EmailServiceName -o json | ConvertFrom-Json
$managedDomain = $domains | Where-Object { $_.name -eq "AzureManagedDomain" } | Select-Object -First 1
$brandDomain = $domains | Where-Object { $_.name -eq $BrandedDomain } | Select-Object -First 1

if (-not $managedDomain) {
    throw "Azure managed ACS email domain was not found."
}

$normalizedSenderUsername = $SenderUsername.Trim().ToLowerInvariant()
Ensure-SenderUsername -DomainName "AzureManagedDomain" -SenderUsername $normalizedSenderUsername
if ($brandDomain) {
    Ensure-SenderUsername -DomainName $BrandedDomain -SenderUsername $normalizedSenderUsername
}

$brandReady = Test-DomainFullyVerified -DomainResource $brandDomain
$activeDomain = if ($PreferBrandedDomain -and $brandReady) { $BrandedDomain } else { $managedDomain.fromSenderDomain }
$managedSender = "$normalizedSenderUsername@$($managedDomain.fromSenderDomain)"
$activeSender = "$normalizedSenderUsername@$activeDomain"

Write-Host ""
Write-Host "ACS Communication Service: $($comm.hostName)"
Write-Host "Immediate sender (already verified): $managedSender"
Write-Host "Auth sender currently configured: $activeSender"

if ($PreferBrandedDomain -and -not $brandReady) {
    Write-Host "Branded domain is not fully verified yet, so the script kept the managed ACS domain active for live sending."
}

if ($brandDomain) {
    Write-Host "Branded sender target after DNS verification: $normalizedSenderUsername@$BrandedDomain"
    Write-Host ""
    Write-Host "DNS records to add in Spaceship for ${BrandedDomain}:"
    foreach ($entryName in @("Domain", "SPF", "DKIM", "DKIM2")) {
        $record = $brandDomain.verificationRecords.$entryName
        if ($null -ne $record) {
            Write-Host ("- {0}: {1} {2} {3}" -f $entryName, $record.type, $record.name, $record.value)
        }
    }
    Write-Host ""
    Write-Host "Current verification states:"
    foreach ($entryName in @("Domain", "SPF", "DKIM", "DKIM2", "DMARC")) {
        $state = $brandDomain.verificationStates.$entryName
        if ($null -ne $state) {
            Write-Host ("- {0}: {1}" -f $entryName, $state.status)
        }
    }
}

Write-Host ""
if ($phoneNumbers -and $phoneNumbers.Count -gt 0) {
    Write-Host "SMS-capable sender numbers linked to this Communication Service:"
    foreach ($number in $phoneNumbers) {
        if ($number.number) {
            Write-Host ("- {0}" -f $number.number)
        }
    }
} else {
    Write-Host "No ACS phone numbers are linked yet. ACS_SMS_FROM must be set after you provision an SMS-capable sender number."
}

if ($WriteToFinagentEnv) {
    $envPath = Join-Path $repoRoot "finagent\.env"
    Set-EnvFileValue -Path $envPath -Name "ACS_EMAIL_CONNECTION_STRING" -Value $keys.primaryConnectionString
    Set-EnvFileValue -Path $envPath -Name "ACS_EMAIL_FROM" -Value $activeSender
    Set-EnvFileValue -Path $envPath -Name "ACS_EMAIL_SENDER_USERNAME" -Value $normalizedSenderUsername
    Set-EnvFileValue -Path $envPath -Name "ACS_EMAIL_DOMAIN" -Value $activeDomain
    Set-EnvFileValue -Path $envPath -Name "ACS_SMS_CONNECTION_STRING" -Value $keys.primaryConnectionString

    Write-Host ""
    Write-Host "Updated local finagent/.env with ACS auth email settings."
    if ($brandReady) {
        Write-Host "The branded domain is ready, so the env file now points auth mail at $BrandedDomain."
    } else {
        Write-Host "The branded domain is not ready yet, so the env file currently points auth mail at the managed ACS domain."
        Write-Host "Re-run this script with -PreferBrandedDomain after $BrandedDomain verifies."
    }
}
