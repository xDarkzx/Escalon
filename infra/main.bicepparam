using './main.bicep'

param image = readEnvironmentVariable('ESCALON_IMAGE')

// Pick a chat model your region offers: az cognitiveservices model list -l <region>
param chatModelName = readEnvironmentVariable('ESCALON_CHAT_MODEL')
param chatModelVersion = readEnvironmentVariable('ESCALON_CHAT_MODEL_VERSION')

param entraAudience = readEnvironmentVariable('ESCALON_ENTRA_AUDIENCE')
param zammadUrl = readEnvironmentVariable('ESCALON_ZAMMAD_URL')
// Read from the environment so the token never lands in a file or in shell history.
param zammadToken = readEnvironmentVariable('ESCALON_ZAMMAD_TOKEN')
