# watsonx Orchestrate Level 2 Context

Purpose: persistent project context for the watsonx Orchestrate corpus, combining the existing public developer documentation crawl manifest with three Level 2 PDF guides.

## Sources Added

- `local://docs/watsonx_orchestrate_l2/client_presentation_watsonx_orchestrate_l2.pdf`
  - Client-facing Level 2 presentation.
  - Pages: 28, non-empty pages: 24.
  - Extracted text hash: `sha256:1223ebf47f36f70cf6e3527e886a792e5399342e16684b2f408c29c5081dd7fe`.
- `local://docs/watsonx_orchestrate_l2/seller_presentation_watsonx_orchestrate_l2.pdf`
  - IBM and Business Partner internal-use seller enablement deck.
  - Pages: 94, non-empty pages: 93.
  - Extracted text hash: `sha256:a7736a7c6f3358df1e2bf13c00291e5a7273b52cea2765a6fe926f4530fa392a`.
- `local://docs/watsonx_orchestrate_l2/watsonx_orchestrate_l2_master_notes.pdf`
  - Compressed Level 2 study notes synthesized from the client and seller decks.
  - Pages: 18, non-empty pages: 18.
  - Extracted text hash: `sha256:ab2ff584d07acdf067e1d28e868095faf3b9a73382af53fa522b24b1f547a8fa`.
- `local://docs/watsonx_orchestrate_l2/watsonx_orchestrate_l3_demo_guide.pdf`
  - Level 3 hands-on demo guide for technical sellers.
  - Pages: 33, non-empty pages: 32.
  - Extracted text hash: `sha256:ecc861916f021cde3bbcba72c8740d1ddbe39c31d0e2c4f728e4eed9e24df78b`.
  - Primary flow: AskIBM orchestration, AskHR payslips/support/holidays/PTO/benefits/employment letter, guardrails, AskIT troubleshooting, and optional Agent Catalog exploration.
- Existing public web source:
  - `https://developer.watson-orchestrate.ibm.com/llms.txt`
  - Used by `config/corpus/watsonx_orchestrate.yaml` to expand into public ADK/developer documentation pages.

## Guardrails

- Treat the client deck as client-facing product and business-value framing.
- Treat the seller deck and master notes as internal study/seller enablement context.
- The decks contain 2025 material. Verify current official sources before repeating roadmap, pricing, packaging, region, compliance, public-preview, catalog, or availability claims.
- Do not present case-study metrics as guaranteed outcomes. Frame them as examples from the deck and baseline each client's own process before discussing impact.
- Do not claim users can see hidden model chain-of-thought. Use client-safe language: traces, tool calls, decisions, observability, source traceability, audit trails, and action history.
- Do not frame the platform as just a chatbot. Its value is orchestration across agents, tools, automations, applications, data, and governed workflows.
- Demo guide screenshots and behavior may differ from the current product. Rehearse the exact prompts in the live environment before presenting.

## Core Product Definition

IBM watsonx Orchestrate is an open, hybrid enterprise platform for coordinating AI agents, assistants, tools, enterprise data, workflows, and business applications so complex work can be completed through a unified experience.

Mental model: traffic controller plus marketplace plus builder plus operations layer for enterprise agents.

Memory hook: fragmentation -> orchestration -> productivity -> governance.

## Problem Framing

- Enterprises accumulate siloed assistants, automations, and domain agents across HR, procurement, sales, customer care, finance, and IT.
- Siloed growth creates tool overload, fragmented user experience, weak governance, and difficulty proving ROI.
- Traditional automation helps structured workflows, but is not enough for dynamic reasoning and cross-system work.
- Cloud-only or domain-only approaches can create lock-in or more isolated "mini agents."

## Capability Map

- Agentic orchestration: supervisor/router/planner that coordinates multiple agents and tools across business processes.
- Agent and Tool Catalog: discovery and reuse layer for IBM, partner, and client-built agents/tools.
- Build or bring agents: no-code Agent Builder/Studio, pre-built agents, custom integrations, Agent Development Kit, and Agent Connect for partner publishing.
- AgentOps: deployment, lifecycle management, tracing, testing, monitoring, debugging, quality evaluation, security, guardrails, and human approvals.

## Agent Building Blocks

Use this model when assessing a use case:

- Purpose: role, scope, personality, and domain boundary.
- Tools: authorized APIs, application actions, RPA flows, data sources, search, or custom code the agent can call.
- Collaborators: other specialized agents the orchestrator can delegate to.
- Knowledge: grounding content, documents, repositories, and enterprise data used for retrieval.
- Glossary: domain terms, synonyms, and definitions.
- Behavior: guidelines, triggers, constraints, and human-in-the-loop checkpoints.

## High-Value Domains

- HR: employee support, talent acquisition, onboarding, learning, performance, payroll, benefits, and manager support.
- Sales: prospecting, product guidance, client outreach, meeting insight, CRM updates, opportunity management, and seller support.
- Procurement: supplier assessment/risk, sourcing, contracts, requisitions, purchase orders, invoices, external workforce, and procurement insights.
- Customer care: self-service, contact-center modernization, agent assist, and operational insights.
- Other functions: finance, supply chain, IT support, order-to-cash, expense management, reporting, and industry-specific workflows.

## Discovery Pattern

Prefer bounded, high-volume, cross-system work where the client can name a business owner and KPI.

Questions to ask:

- Which employees or customers are forced across multiple applications to finish one task?
- Which AI, automation, or assistant pilots already exist, and why did they not scale?
- What systems, APIs, data owners, permissions, approvals, and exception paths are involved?
- What trust, security, governance, or audit constraints matter before an agent can act?
- What baseline metrics exist: volume, cycle time, time saved, error/rework, containment, cost, satisfaction, and adoption?

## Demo Pattern

- Start with a natural-language request in a familiar business domain.
- Show the orchestrator selecting/coordinating specialist agents and tools.
- Include a human confirmation before a high-impact action.
- Show the completed transaction, communication, or recommendation.
- Show traceability, observability, source grounding, and governance controls.

## Level 3 Demo Flow

- Open with the problem: employees lose time navigating HR, IT, sales, and support systems; enterprises need one governed engagement layer across agents and tools.
- Show AskIBM as the orchestrator agent, then let it route to AskHR for payslips and HR support.
- Use Show Reasoning to explain tool execution, source grounding, country code, and action traceability.
- Demonstrate personalization with two employee profiles from different countries for holiday lookup.
- Demonstrate multi-intent planning with a PTO request that checks available balance and interprets relative dates.
- Demonstrate business-rule grounding with health-plan recommendation and changed user input.
- Demonstrate guardrails by entering a toxic-language prompt and showing safe HR redirection.
- Demonstrate multi-system integration with employment verification letter generation, compensation lookup, and email sending.
- Demonstrate cross-domain switching by moving from AskHR to AskIT for device troubleshooting and replacement eligibility.
- Optional: show the Agent Catalog to connect the live demo to broader reuse, prebuilt agents, and faster time to value.

## Common Traps

- Treating Orchestrate as only a chat interface.
- Promising fully autonomous action without permission boundaries or human approval.
- Hand-waving integration without checking APIs, identity, permissions, data quality, and source systems.
- Quoting dated pricing, roadmap, region, compliance, or catalog statements as current.
- Using case-study results as guaranteed ROI.
- Saying users can view hidden model reasoning.
- Starting from "we need an agent" instead of measurable workflow friction.
