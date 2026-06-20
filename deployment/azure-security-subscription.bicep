targetScope = 'subscription'

@allowed([
  'focused'
  'all'
])
param defenderScopeMode string = 'focused'

param enableDefender bool = true
param defenderPlans array = [
  'VirtualMachines'
  'AppServices'
  'SqlServers'
  'StorageAccounts'
  'Containers'
  'KeyVaults'
]

resource defenderPricing 'Microsoft.Security/pricings@2024-01-01' = [
  for defenderPlan in defenderPlans: if (enableDefender && defenderScopeMode == 'focused') {
    name: defenderPlan
    properties: {
      pricingTier: 'Standard'
    }
  }
]

output defenderPlansApplied array = enableDefender && defenderScopeMode == 'focused' ? defenderPlans : []
