# Deploying to Azure

> **Checked in CI on every pull request:** the Bicep compiles and lints clean, and the container
> image builds and passes its health check.

Everything runs keyless. The app uses a user-assigned managed identity; Azure OpenAI and AI
Search have API-key auth disabled. The only secret, the Zammad token, lives in Key Vault.

## 1. Register the API in Entra ID

Callers (Copilot Studio, or anything calling `/api/chat`) request an access token for this
app with the `Helpdesk.Use` scope. Escalon checks the issuer, audience, expiry and scope, and
takes the user's identity from the token.

```bash
APP_ID=$(az ad app create --display-name "Escalon API" --sign-in-audience AzureADMyOrg --query appId -o tsv)
az ad app update --id "$APP_ID" --identifier-uris "api://$APP_ID"

SCOPE_ID=$(python -c "import uuid; print(uuid.uuid4())")
az ad app update --id "$APP_ID" --set api="{
  \"requestedAccessTokenVersion\": 2,
  \"oauth2PermissionScopes\": [{
    \"id\": \"$SCOPE_ID\", \"value\": \"Helpdesk.Use\", \"type\": \"User\", \"isEnabled\": true,
    \"adminConsentDisplayName\": \"Use Escalon IT support\",
    \"adminConsentDescription\": \"Search IT articles and file helpdesk tickets as the signed-in user.\",
    \"userConsentDisplayName\": \"Use Escalon IT support\",
    \"userConsentDescription\": \"Search IT articles and file helpdesk tickets as you.\"
  }]
}"
az ad sp create --id "$APP_ID"
echo "ESCALON_ENTRA_AUDIENCE=api://$APP_ID"
```

## 2. Publish the image

```bash
docker build -t ghcr.io/<owner>/escalon:$(git rev-parse --short HEAD) .
docker push ghcr.io/<owner>/escalon:$(git rev-parse --short HEAD)
```

## 3. Deploy the infrastructure

Pick a chat model your region offers (`az cognitiveservices model list -l <region>`).

```bash
az group create -n rg-escalon -l australiaeast

export ESCALON_IMAGE=ghcr.io/<owner>/escalon:<sha>
export ESCALON_CHAT_MODEL=<model name> ESCALON_CHAT_MODEL_VERSION=<version>
export ESCALON_ENTRA_AUDIENCE=api://<app id>
export ESCALON_ZAMMAD_URL=https://<your zammad>
read -rs ESCALON_ZAMMAD_TOKEN && export ESCALON_ZAMMAD_TOKEN   # not echoed, not in history

az deployment group create -g rg-escalon -f infra/main.bicep -p infra/main.bicepparam
```

Outputs include `mcpEndpoint`, `searchEndpoint` and `openaiEndpoint`.

## 4. Index the knowledge base into Azure AI Search

Run once from a workstation. Give your own account the roles the app has (Search Index Data
Contributor, Search Service Contributor, Cognitive Services OpenAI User), `az login`, then:

```bash
ESCALON_PROFILE=azure \
ESCALON_AZURE_OPENAI_ENDPOINT=<openaiEndpoint> ESCALON_AZURE_SEARCH_ENDPOINT=<searchEndpoint> \
ESCALON_CHAT_MODEL=<model name> ESCALON_EMBEDDING_MODEL=text-embedding-3-small \
ESCALON_EMBEDDING_DIMENSIONS=1536 ESCALON_AUTH_MODE=disabled ESCALON_DEV_USER_EMAIL=you@example.com \
uv run escalon fetch-kb && uv run escalon ingest
```

Then re-run the evals against the Azure profile and commit the results next to the local ones.

## 5. Put it in Teams with Copilot Studio

In Copilot Studio, create an agent and add a tool of type **Model Context Protocol** pointing
at `mcpEndpoint` (streamable HTTP), with OAuth 2.0 authentication against the Entra app from
step 1 and the `api://<app id>/Helpdesk.Use` scope. Copilot Studio then calls `search_kb`,
`find_open_tickets` and `create_ticket` as the signed-in Teams user. Publish the agent to the
Microsoft Teams channel.

## Operational notes

- **Single replica.** Per-user tool state (which articles a user was shown, which tickets
  they filed this session) is held in memory, so `maxReplicas` is 1. Scaling out means moving
  that state to a shared store, such as Redis.
- **Ticket search lag.** Zammad indexes new tickets 2.5-5 s after creation. Escalon covers the
  gap within a session; across sessions a duplicate filed in that window is possible.
