param(
    [string]$ResourceGroup = "rg-PROSPEKTLAB",
    [string]$EmailServiceName = "prospektlab-email",
    [string]$AcsDomain = "notify.prospektlab.com",
    [string]$M365Domain = "prospektlab.com"
)

$ErrorActionPreference = "Stop"

function Get-DnsSummary {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Type
    )

    try {
        $records = Resolve-DnsName -Name $Name -Type $Type -ErrorAction Stop
    } catch {
        return @()
    }

    $items = @()
    foreach ($record in $records) {
        switch ($Type.ToUpperInvariant()) {
            "TXT" {
                $items += (($record.Strings | ForEach-Object { $_.Trim() }) -join " | ")
            }
            "CNAME" {
                $items += ($record.NameHost.Trim())
            }
            "MX" {
                $items += ("{0} (pref {1})" -f $record.NameExchange.Trim(), $record.Preference)
            }
            default {
                $items += ($record | Out-String).Trim()
            }
        }
    }
    return $items
}

function Show-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host $Title
    Write-Host ("-" * $Title.Length)
}

Show-Section "Azure ACS"
$acs = az communication email domain show `
    --resource-group $ResourceGroup `
    --email-service-name $EmailServiceName `
    --domain-name $AcsDomain `
    -o json | ConvertFrom-Json

Write-Host "Domain: $AcsDomain"
foreach ($entryName in @("Domain", "SPF", "DKIM", "DKIM2", "DMARC")) {
    $state = $acs.verificationStates.$entryName
    if ($null -ne $state) {
        $line = "- {0}: {1}" -f $entryName, $state.status
        if ($state.errorCode) {
            $line += " ($($state.errorCode))"
        }
        Write-Host $line
    }
}

Write-Host "Public DNS for $AcsDomain TXT:"
$acsTxt = Get-DnsSummary -Name $AcsDomain -Type "TXT"
if ($acsTxt.Count -eq 0) {
    Write-Host "- none found"
} else {
    $acsTxt | ForEach-Object { Write-Host "- $_" }
}

foreach ($selector in @("selector1-azurecomm-prod-net._domainkey.$AcsDomain", "selector2-azurecomm-prod-net._domainkey.$AcsDomain")) {
    Write-Host "Public DNS for $selector CNAME:"
    $cname = Get-DnsSummary -Name $selector -Type "CNAME"
    if ($cname.Count -eq 0) {
        Write-Host "- none found"
    } else {
        $cname | ForEach-Object { Write-Host "- $_" }
    }
}

Show-Section "Microsoft 365"
$token = az account get-access-token --resource-type ms-graph --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token" }
$m365 = Invoke-RestMethod -Method Get -Uri "https://graph.microsoft.com/v1.0/domains/$M365Domain" -Headers $headers
$org = Invoke-RestMethod -Method Get -Uri "https://graph.microsoft.com/v1.0/organization" -Headers $headers
$skus = Invoke-RestMethod -Method Get -Uri "https://graph.microsoft.com/v1.0/subscribedSkus" -Headers $headers

Write-Host "Tenant: $($org.value[0].displayName)"
Write-Host "Domain: $M365Domain"
Write-Host "Verified in tenant: $($m365.isVerified)"
Write-Host "Supported services: $((@($m365.supportedServices) -join ', '))"
Write-Host "Subscribed SKUs: $(@($skus.value).Count)"

Write-Host "Public DNS for $M365Domain TXT:"
$m365Txt = Get-DnsSummary -Name $M365Domain -Type "TXT"
if ($m365Txt.Count -eq 0) {
    Write-Host "- none found"
} else {
    $m365Txt | ForEach-Object { Write-Host "- $_" }
}

Write-Host "Public DNS for $M365Domain MX:"
$m365Mx = Get-DnsSummary -Name $M365Domain -Type "MX"
if ($m365Mx.Count -eq 0) {
    Write-Host "- none found"
} else {
    $m365Mx | ForEach-Object { Write-Host "- $_" }
}

Write-Host ""
Write-Host "Expected Microsoft 365 verification token for this tenant:"
$dnsRecords = Invoke-RestMethod -Method Get -Uri "https://graph.microsoft.com/v1.0/domains/$M365Domain/verificationDnsRecords" -Headers $headers
foreach ($record in @($dnsRecords.value)) {
    if ($record.recordType -eq "Txt") {
        Write-Host ("- TXT {0} {1}" -f $record.label, $record.text)
    } elseif ($record.recordType -eq "Mx") {
        Write-Host ("- MX {0} {1} pref {2}" -f $record.label, $record.mailExchange, $record.preference)
    }
}
