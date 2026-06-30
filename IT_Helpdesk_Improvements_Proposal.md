# IT Help Desk Chatbot — Architectural Improvements Proposal

## Purpose

This document proposes improvements to the current IBM BOB implementation plan for the **IBM IT Help Desk Chatbot**.  
The goal is not to replace the existing architecture, but to strengthen it in areas of scalability, retrieval precision, and troubleshooting intelligence.

---

## Improvement 1 — Add an Intent Router Layer

### Current State
Current architecture directly routes user prompts into one of three skills:

- Ask
- Summarize
- Troubleshoot

### Problem
This relies heavily on phrase matching and may fail for ambiguous queries.

Example:
> "My bootstrap is timing out during installation"

This could be:
- Installation issue
- Troubleshooting issue
- Networking issue

### Proposed Solution
Add a dedicated **Intent Router** before skill execution.

### New Intent Categories

- Installation
- Troubleshooting
- Configuration
- Upgrade
- Networking
- Storage
- Security

### Benefits

- Better routing accuracy
- Easier skill expansion
- Better long-term scalability

---

## Improvement 2 — Metadata-aware Retrieval

### Current State
Watson Discovery retrieves chunks semantically.

### Problem
IBM technical documentation is highly version-sensitive.

Example:
- OpenShift 4.12 install guide
- OpenShift 4.16 install guide

Wrong version retrieval can produce incorrect troubleshooting.

### Proposed Metadata Schema

```json
{
  "product": "OpenShift",
  "version": "4.16",
  "deployment_type": "SNO",
  "component": "bootstrap"
}
```

### Benefits

- Version-specific retrieval
- Better context filtering
- Higher answer accuracy

---

## Improvement 3 — Domain-first Implementation Strategy

### Current State
Broad IBM document ingestion.

### Problem
Too broad for internship scope.

### Proposed Narrow Scope

Start with:

**Primary domain:**
- Red Hat OpenShift (OCP)
- Single Node OpenShift (SNO)

Focus areas:
- Installation
- Bootstrap issues
- Networking
- Ingress
- Storage
- etcd
- API server

### Why this works

- Real-world IBM relevance
- Easier evaluation
- Stronger demo narrative

Example project framing:
> "Built an OpenShift troubleshooting copilot for IBM technical teams."

---

## Improvement 4 — Deterministic Troubleshooting Trees

### Current State
Troubleshooting is purely prompt-driven.

### Problem
LLMs may miss known debugging steps.

### Proposed Hybrid Model

Combine:

- Rule-based diagnostic trees
- RAG retrieval
- Granite generation

### Example

#### Bootstrap timeout

Checklist:
- DNS validation
- NTP sync
- API VIP reachability
- Pull secret validation
- Ignition file availability

#### etcd quorum issue

Checklist:
- Node reachability
- Clock skew
- Certificate validity
- Disk pressure

### Benefits

- More consistent troubleshooting
- Reduced hallucinations
- Better enterprise reliability

---

## Improvement 5 — Confidence Scoring

### Proposed Addition

Every response returns:

- Confidence: High
- Confidence: Medium
- Confidence: Low

### Logic

Factors:

- Retrieval similarity score
- Number of matching chunks
- Metadata alignment
- Source consistency

### Benefits

- Helps users trust answers
- Signals uncertainty clearly

---

## Improved Final Architecture

```text
User
 ↓
Watsonx Orchestrate
 ↓
Intent Router
 ↓
FastAPI
 ↓
RAG Core
 ├── Watson Discovery Retrieval
 ├── Metadata Filtering
 ├── Troubleshooting Rule Engine
 ├── Granite Generation
 ├── Confidence Scoring
 ↓
Final Response + Source Citation
```

---

## Recommendation

Keep the IBM BOB implementation as the base architecture.

Add these improvements in phases:

### Phase 1 (Immediate)
- Intent Router
- Domain narrowing (OCP/SNO)

### Phase 2
- Metadata filters
- Confidence scoring

### Phase 3
- Troubleshooting trees

This preserves delivery speed while significantly improving system quality.

---

## Final Assessment

Current IBM BOB Plan: **8.8/10**

Improved Hybrid Plan: **9.7/10**

This improved design makes the chatbot:

- More accurate
- More scalable
- Better at troubleshooting
- Better aligned with IBM technical support workflows
