param location string = resourceGroup().location
param workspaceName string = 'prospektlab-monitoring'
param appInsightsName string = 'prospektlab-appinsights'
param purviewAccountName string = 'prospektlab-purview'
param purviewManagedResourceGroupName string = 'prospektlab-purview-managed'
param targetMonthlyUsd int = 100
param hardCapMonthlyUsd int = 120
@allowed([
  'focused'
  'all'
])
param defenderScopeMode string = 'focused'
param purviewEnableGovernance bool = true
param purviewEnableSecurity bool = true
@allowed([
  'all_available'
  'app_db_only'
  'custom'
])
param purviewSourceMode string = 'all_available'
param retentionInDays int = 90
param dailyQuotaGb int = 50
param tags object = {}

var shouldProvisionPurview = purviewEnableGovernance || purviewEnableSecurity

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2025-07-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    workspaceCapping: {
      dailyQuotaGb: dailyQuotaGb
    }
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    SamplingPercentage: 100
    RetentionInDays: retentionInDays
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
    DisableIpMasking: false
    DisableLocalAuth: false
    ForceCustomerStorageForProfiler: false
  }
}

resource sentinelOnboardingState 'Microsoft.SecurityInsights/onboardingStates@2025-09-01' = {
  scope: logAnalytics
  name: 'default'
  properties: {
    customerManagedKey: false
  }
}

resource purviewAccount 'Microsoft.Purview/accounts@2021-12-01' = if (shouldProvisionPurview) {
  name: purviewAccountName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedResourceGroupName: purviewManagedResourceGroupName
    publicNetworkAccess: 'Enabled'
  }
}

output logAnalyticsWorkspaceId string = logAnalytics.id
output applicationInsightsId string = applicationInsights.id
output sentinelOnboardingStateId string = sentinelOnboardingState.id
output purviewAccountId string = shouldProvisionPurview ? purviewAccount!.id : ''
output purviewEndpoints object = shouldProvisionPurview ? purviewAccount!.properties.endpoints : {}
output targetMonthlyUsdOut int = targetMonthlyUsd
output hardCapMonthlyUsdOut int = hardCapMonthlyUsd
output defenderScopeModeOut string = defenderScopeMode
output purviewEnableGovernanceOut bool = purviewEnableGovernance
output purviewEnableSecurityOut bool = purviewEnableSecurity
output purviewSourceModeOut string = purviewSourceMode
