// Escalon on Azure: Azure AI Search + Azure OpenAI (Foundry) + Container Apps.
// Keyless: the app authenticates with a user-assigned managed identity and RBAC;
// local (API-key) auth is disabled on Search and OpenAI.

targetScope = 'resourceGroup'

@description('Short name used to derive resource names.')
@minLength(3)
@maxLength(12)
param name string = 'escalon'

param location string = resourceGroup().location

@description('Container image for the app, e.g. ghcr.io/<owner>/escalon:<tag>.')
param image string

@description('Chat model to deploy. Check availability in your region first.')
param chatModelName string
param chatModelVersion string
param chatModelCapacity int = 10

param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'
param embeddingDimensions int = 1536
param embeddingCapacity int = 10

@description('Search tier. "free" allows one service per subscription.')
@allowed(['free', 'basic'])
param searchSku string = 'free'

@description('Entra tenant that issues tokens for callers.')
param entraTenantId string = tenant().tenantId

@description('Application ID URI of the Escalon API app registration, e.g. api://<client-id>.')
param entraAudience string

param zammadUrl string

@secure()
@description('Zammad API token. Stored in Key Vault, never in app settings.')
param zammadToken string

var suffix = uniqueString(resourceGroup().id, name)
// Built-in Azure role definition IDs (public, identical in every tenant).
var roles = {
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6' // gitleaks:allow (public built-in role ID)
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs-${suffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-id-${suffix}'
  location: location
}

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: '${name}-search-${suffix}'
  location: location
  sku: { name: searchSku }
  properties: {
    replicaCount: 1
    partitionCount: 1
    disableLocalAuth: true
    publicNetworkAccess: 'enabled'
  }
}

resource openai 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: '${name}-ai-${suffix}'
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: '${name}-ai-${suffix}'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openai
  name: chatModelName
  sku: { name: 'GlobalStandard', capacity: chatModelCapacity }
  properties: {
    model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion }
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openai
  name: embeddingModelName
  sku: { name: 'Standard', capacity: embeddingCapacity }
  properties: {
    model: { format: 'OpenAI', name: embeddingModelName, version: embeddingModelVersion }
  }
  dependsOn: [chatDeployment] // the account accepts one deployment operation at a time
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${name}-${take(suffix, 8)}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource zammadSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'zammad-token'
  properties: { value: zammadToken }
}

resource searchDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, identity.id, roles.searchIndexDataContributor)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
  }
}

resource searchServiceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, identity.id, roles.searchServiceContributor)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
  }
}

resource openaiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openai
  name: guid(openai.id, identity.id, roles.cognitiveServicesOpenAIUser)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
  }
}

resource vaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, identity.id, roles.keyVaultSecretsUser)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-env-${suffix}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var appName = '${name}-app'
var publicUrl = 'https://${appName}.${environment.properties.defaultDomain}'

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      secrets: [
        {
          name: 'zammad-token'
          keyVaultUrl: zammadSecret.properties.secretUri
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'escalon'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'ESCALON_PROFILE', value: 'azure' }
            { name: 'ESCALON_AZURE_OPENAI_ENDPOINT', value: openai.properties.endpoint }
            { name: 'ESCALON_AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
            { name: 'ESCALON_CHAT_MODEL', value: chatDeployment.name }
            { name: 'ESCALON_EMBEDDING_MODEL', value: embeddingDeployment.name }
            { name: 'ESCALON_EMBEDDING_DIMENSIONS', value: string(embeddingDimensions) }
            { name: 'ESCALON_AUTH_MODE', value: 'entra' }
            { name: 'ESCALON_ENTRA_TENANT_ID', value: entraTenantId }
            { name: 'ESCALON_ENTRA_AUDIENCE', value: entraAudience }
            { name: 'ESCALON_PUBLIC_URL', value: publicUrl }
            { name: 'ESCALON_ZAMMAD_URL', value: zammadUrl }
            { name: 'ESCALON_ZAMMAD_TOKEN', secretRef: 'zammad-token' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8000 }
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/healthz', port: 8000 }
              periodSeconds: 10
            }
          ]
        }
      ]
      // Per-user tool state is held in memory, so exactly one replica (see docs/design.md).
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
  dependsOn: [vaultRole, searchDataRole, searchServiceRole, openaiRole]
}

output appUrl string = publicUrl
output mcpEndpoint string = '${publicUrl}/mcp'
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output openaiEndpoint string = openai.properties.endpoint
output identityClientId string = identity.properties.clientId
