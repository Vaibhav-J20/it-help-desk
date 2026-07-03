# Code Engine Deployment Guide
# OpenShift & SNO Technical Support Copilot — FastAPI on IBM Code Engine

## Prerequisites
- IBM Cloud CLI: https://cloud.ibm.com/docs/cli
- Code Engine plugin: `ibmcloud plugin install code-engine`
- Container Registry plugin: `ibmcloud plugin install container-registry`
- Docker running locally
- TechZone environment provisioned (Agentic AI watsonx Orchestrate bundle)

---

## Step 1 — Login to IBM Cloud

```bash
ibmcloud login --sso
# Select the region matching your TechZone environment (us-south)
```

---

## Step 2 — Set up Container Registry

```bash
# Target the Container Registry region
ibmcloud cr region-set us-south

# Login Docker to IBM Container Registry
ibmcloud cr login

# Create a namespace (once only)
ibmcloud cr namespace-add it-helpdesk-poc
```

---

## Step 3 — Build and Push the Docker Image

```bash
cd /path/to/IT-help-desk

# Build
docker build -t us.icr.io/it-helpdesk-poc/support-api:latest .

# Push
docker push us.icr.io/it-helpdesk-poc/support-api:latest

# Verify
ibmcloud cr image-list
```

---

## Step 4 — Create the Code Engine Project

```bash
ibmcloud ce project create --name it-helpdesk-poc
ibmcloud ce project select --name it-helpdesk-poc
```

---

## Step 5 — Create a Registry Secret

```bash
# Allow Code Engine to pull from Container Registry
ibmcloud ce secret create --format registry \
  --name icr-secret \
  --server us.icr.io \
  --username iamapikey \
  --password YOUR_IBM_CLOUD_API_KEY
```

---

## Step 6 — Deploy the Application

Replace all YOUR_* values with real values. Never put secrets in git.

```bash
ibmcloud ce application create \
  --name support-api \
  --image us.icr.io/it-helpdesk-poc/support-api:latest \
  --registry-secret icr-secret \
  --port 8080 \
  --min-scale 1 \
  --max-scale 2 \
  --cpu 0.5 \
  --memory 1G \
  --env IBM_CLOUD_API_KEY=YOUR_IBM_CLOUD_API_KEY \
  --env WATSONX_URL=https://us-south.ml.cloud.ibm.com \
  --env WATSONX_PROJECT_ID=YOUR_WATSONX_PROJECT_ID \
  --env WATSONX_EMBEDDING_MODEL_ID=ibm/slate-125m-english-rtrvr-v2 \
  --env WATSONX_CHAT_MODEL_ID=meta-llama/llama-3-3-70b-instruct \
  --env OPENSEARCH_INDEX_CHUNKS=knowledge_chunks_v1 \
  --env OPENSEARCH_INDEX_DOCS=knowledge_documents_v1 \
  --env API_KEY_SECRET=YOUR_STRONG_RANDOM_SECRET \
  --env ENABLE_RERANKER=false \
  --env RRF_K=60 \
  --env LOG_LEVEL=INFO
  # OPENSEARCH_URL is set separately — see Step 7
```

---

## Step 7 — Expose Local OpenSearch for the Demo

OpenSearch runs locally on your laptop. During the demo, expose it publicly:

```bash
# Install localtunnel (one time)
npm install -g localtunnel

# Start tunnel — run this BEFORE the demo, keep it running
lt --port 9200 --subdomain it-helpdesk-opensearch
# This gives you: https://it-helpdesk-opensearch.loca.lt
```

Then update the Code Engine app with the tunnel URL:

```bash
ibmcloud ce application update \
  --name support-api \
  --env OPENSEARCH_URL=https://it-helpdesk-opensearch.loca.lt \
  --env OPENSEARCH_USERNAME= \
  --env OPENSEARCH_PASSWORD=
```

---

## Step 8 — Get the Public URL

```bash
ibmcloud ce application get --name support-api --output url
# Returns something like: https://support-api.abc123.us-south.codeengine.appdomain.cloud
```

Test it:
```bash
curl https://support-api.abc123.us-south.codeengine.appdomain.cloud/healthz
# Should return: {"status":"ok"}
```

---

## Step 9 — Update on New Code

```bash
docker build -t us.icr.io/it-helpdesk-poc/support-api:latest .
docker push us.icr.io/it-helpdesk-poc/support-api:latest
ibmcloud ce application update --name support-api --image us.icr.io/it-helpdesk-poc/support-api:latest
```

---

## Sharing the URL with Anush (for Orchestrate setup)

Once deployed, give Anush:
1. The public HTTPS URL
2. The API_KEY_SECRET value (over IBM internal chat only — never git)

Anush will import `/openapi.json` from that URL into watsonx Orchestrate.
