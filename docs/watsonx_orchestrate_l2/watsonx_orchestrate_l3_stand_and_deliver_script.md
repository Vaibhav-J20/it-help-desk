# watsonx Orchestrate Level 3 Stand-and-Deliver Script

Purpose: polished demo script for a manager-reviewed stand-and-deliver presentation based on the Level 3 hands-on demo guide and the Level 2 positioning notes.

Recommended duration: 18-25 minutes. If you have less time, skip the optional Agent Catalog section and shorten the quantitative examples.

## Delivery Style

Do not sound like you are reading a lab manual. Treat the UI actions as proof points in a story:

- Problem: enterprise work is fragmented across HR, IT, sales, finance, procurement, and support systems.
- Solution: watsonx Orchestrate acts as a governed system of engagement across agents, tools, data, and applications.
- Proof: each demo step shows an employee completing work through natural language while the platform routes, grounds, acts, confirms, and traces the outcome.
- Value: faster task completion, fewer tickets, reduced subject-matter-expert burden, better governance, and reuse of existing enterprise systems.

Use client-safe language:

- Say "reasoning view", "trace", "tool calls", "source grounding", and "auditability."
- Do not say users can see hidden model chain-of-thought.
- Treat time-savings numbers as illustrative demo-guide examples, not universal guarantees.
- Avoid promising current pricing, roadmap, compliance, or region availability without checking the latest official source.

## Pre-Demo Setup

Before the review, prepare:

- Open the watsonx Orchestrate demo environment and sign in with your w3id.
- Keep the primary tab on your own profile.
- Open a second tab with a different employee profile from another supported country, such as Canada, United States, or Brazil.
- In the primary tab, choose AskIBM from the agent list.
- Confirm each prompt works in your environment before presenting.
- If a prompt behaves differently, keep going and explain that foundation-model outputs can vary while the core orchestration pattern remains the same.

## Opening

Say:

"Hello everyone. Today I will demonstrate IBM watsonx Orchestrate, an agentic AI and automation platform designed to help employees complete real business work across systems, not just ask questions in a chatbot.

In most enterprises, employees already have many systems: HR platforms, IT service tools, CRM systems, procurement applications, knowledge bases, and automation workflows. The challenge is that work does not usually stay inside one system. A simple employee request may require identity, policy, business rules, data lookup, approvals, ticket creation, and communication.

watsonx Orchestrate provides a unified system of engagement for that kind of work. It can coordinate specialized agents, tools, enterprise data, and existing applications through a conversational experience while preserving governance, role-based access, human approvals, and traceability.

In this demo, I will show AskIBM acting as the orchestrator. It will route requests to specialist agents like AskHR and AskIT, use backend tools, retrieve personalized information, ask for confirmation where needed, and show traceability through the reasoning view."

Transition:

"I will start with a very common employee scenario: getting pay information and raising an HR support request."

## 1. Select AskIBM

Screen action:

- Click the agent list.
- Select AskIBM.

Say:

"I am starting in AskIBM. Think of AskIBM as the entry point for the employee. The user does not need to know which backend system handles the task. The platform interprets the request and routes it to the right specialized agent or tool.

That is important because the business value is not only the chat interface. The value is orchestration: connecting identity, knowledge, tools, workflows, and enterprise systems behind a single governed experience."

## 2. View Payslips

Prompt:

```text
Get my payslips
```

After response, say:

"Here, AskIBM routes my request to AskHR. AskHR retrieves my payslip information using my identity, so I do not have to navigate a payroll portal or search through multiple HR screens.

This is also where enterprise control matters. Role-based access means I should only see my own pay information. In a production environment, the agent is not simply generating an answer from memory. It is using authorized tools and enterprise context."

Value point:

"For an employee, this removes friction. For HR and payroll teams, it reduces repetitive requests. The demo guide frames this as saving time compared with manual portal navigation, but the exact business impact would depend on request volume, process design, and adoption."

Transition:

"Now I will show what happens when the employee sees an issue and needs support."

## 3. Open an HR Support Ticket

Prompt:

```text
I need HR support
```

When AskHR offers help, enter:

```text
There's an issue with the amount on my October 1 - October 15, 2025 payslip
```

If prompted:

- Confirm the ticket title.
- Set urgency to:

```text
medium
```

After ticket creation, click thumbs up.

Say:

"This is a good example of moving from question answering into action. AskHR understands that this is not just an FAQ question. The user has a payroll issue, so the system collects the necessary context, categorizes the request, and creates a support ticket.

This is where agentic AI becomes practical. The agent is not replacing the HR team; it is handling the repetitive intake and routing work so HR professionals can focus on exceptions, judgment, and higher-value support."

Explain the thumbs up:

"I am also giving feedback with the thumbs-up control. That feedback loop is part of operating agentic systems responsibly: we need ways to measure whether the answer or action was useful."

Transition:

"Next, I will demonstrate personalization and location-aware responses."

## 4. Verify Remaining Holidays

Prompt in primary tab:

```text
Can you show me the holidays I have left for the rest of the year?
```

Click Show Reasoning.

Say:

"The response is personalized to my profile. When I open the reasoning view, I can see that the system used a holiday-calendar tool and passed my country code as context.

For a client, the important point is that watsonx Orchestrate can inherit user context from enterprise identity and connected systems. The user does not have to enter details the organization already knows, and the agent can use that context to retrieve the correct result."

Screen action:

- Click profile/name in lower-left.
- Show country.

Say:

"This connects to role-based access and single sign-on. The experience feels simple for the user, but behind the scenes the system is respecting who I am, where I am, and what I am allowed to access."

Second tab:

- Switch to different-country profile.
- Enter the same prompt:

```text
Can you show me the holidays I have left for the rest of the year?
```

Say:

"In this second tab, I am using a different employee profile from a different country. The same natural-language request returns country-specific holidays.

This is a simple screen moment, but it proves a larger enterprise concept: a single conversational entry point can adapt based on identity, policy, location, and backend data."

Transition:

"Now I will move from retrieving information to planning an action with conditions."

## 5. Schedule a Vacation Day

Return to primary tab.

Prompt:

```text
Book a personal choice holiday for the Wednesday before Christmas, but only if I have personal holidays left to use
```

Click Show Reasoning.

Say:

"This request contains multiple intentions. I am asking the system to interpret a relative date, check whether I have a personal holiday balance, and only proceed if the condition is true.

In the reasoning view, we can see the system using a time-off balance tool and stepping through the request. This is the difference between a simple assistant and an agentic workflow. The platform is not only answering; it is planning, checking, and acting with constraints."

Add product context:

"For enterprise adoption, that constraint matters. We do not want agents taking action blindly. We want them to check policy, validate data, and include human confirmation when the action affects records or entitlements."

Transition:

"Next I will show business-rule-based recommendation, which is useful because not every decision should be left to a language model."

## 6. Find a Health Plan

Prompt:

```text
Can you help recommend a health plan?
```

When prompted, provide:

```text
I'm 35
```

```text
Happily married with 2 kids
```

```text
We went to the doctor 2 times last year
```

If the agent asks for all inputs at once, answer:

```text
35, married with 2 kids, 2 doctor visits
```

After recommendation, correct the input:

```text
Actually, we went to the doctor 5 times
```

Click Show Reasoning.

Say:

"This part demonstrates dynamic adjustment. I gave the agent information, it made a recommendation, and then I corrected one of the inputs. The recommendation changes based on the updated context.

The key point is that this recommendation is grounded in business rules and connected tools. For clients, that is essential. In sensitive areas like benefits, HR, finance, or procurement, the answer should not be a free-form guess. It should be grounded in approved policy, rules, and data sources."

Add value:

"This also shows how watsonx Orchestrate can become the single entry point even when the final destination is another provider or HR system. The employee gets guided help, while the enterprise keeps the policy logic and system-of-record controls intact."

Transition:

"Now I will intentionally give the system an unsafe or emotional prompt to show guardrails."

## 7. Test Guardrails

Prompt:

```text
I hate my manager
```

Say:

"This prompt is intentionally uncomfortable, because responsible AI has to handle real user behavior, not just clean demo prompts.

Instead of escalating the language or producing an inappropriate response, watsonx Orchestrate redirects the user toward proper HR support channels. This shows governance in action. The platform needs to be helpful, but also safe, compliant, and aligned with enterprise policy."

Add product context:

"For a client, this matters because agentic systems operate close to real processes and real employees. Guardrails, escalation paths, role-based access, and auditability are not optional extras. They are what make production use credible."

Transition:

"Next I will show a richer example that crosses multiple enterprise systems."

## 8. Generate an Employment Verification Letter

Prompt:

```text
Generate an employment verification letter
```

When prompted:

- Recipient:

```text
just to me
```

- Include salary details:

```text
yes
```

- Confirm generating and emailing the letter:

```text
confirmed
```

After success, click Show Reasoning.

Say:

"This request demonstrates multi-system integration. The agent generates an employment verification letter, retrieves compensation information, and uses an email tool to send the output.

In the reasoning view, we can show the tool calls involved. For example, the agent can call a letter-generation tool, retrieve current compensation from an HR system, and then use a mail-sending tool."

Point out:

"This complements systems like Workday, SAP SuccessFactors, or other HR platforms. The point is not rip and replace. The point is to orchestrate the systems the client already has and make the experience simpler for the employee."

Use links if available:

"In this demo, the generated letter and sample email are provided through demo links rather than a real inbox. In production, the same pattern would be connected to the client's approved document, email, identity, and HR systems."

Value point:

"This is a strong example for a manager review because it shows real work: data lookup, document generation, sensitive information confirmation, and communication. It also shows why human-in-the-loop matters before sending personal information."

Transition:

"So far we have stayed mostly in HR. Now I will show how the experience can switch domains without forcing the user to switch systems."

## 9. Troubleshoot a Slow Laptop and Request a Replacement

Prompt:

```text
My laptop is running slow, can I get a new device?
```

When asked which device:

```text
it's my Apple device
```

Say:

"Notice that I did not explicitly choose an IT agent. I simply described my problem. AskIBM can route the request from the HR-style interaction to AskIT because the intent has changed.

The agent shows my devices, offers to run a diagnostic, checks the device condition, and determines whether it is eligible for replacement. This is the same orchestration idea applied to IT service management."

Add product context:

"In many enterprises, this type of issue would become a service desk ticket or require the employee to search a device portal. Here, the agent can connect to device inventory, diagnostic tools, and ticketing systems such as ServiceNow. The user gets a simpler experience, and IT can reduce repetitive triage."

Transition:

"If time allows, I will connect this demo to the broader watsonx Orchestrate catalog."

## 10. Optional Agent Catalog Section

Only use this section if you have a provisioned watsonx Orchestrate instance and enough time.

Screen action:

- Open Agent Catalog.
- Click HR.
- Click IT.
- Click Sales.

Say:

"The Agent Catalog is important because clients do not want every team building from scratch. The catalog gives them a place to discover and reuse prebuilt agents, tools, and templates across domains such as HR, IT, sales, procurement, and customer care.

This accelerates time to value. A client can begin with a prebuilt pattern, connect it to their systems, apply their governance, and customize where needed."

Add Level 2 positioning:

"This is one of the four core pillars of the platform: orchestration, catalog, build or bring agents, and AgentOps. Together, those pillars help the organization avoid agent sprawl. Instead of many disconnected assistants, the enterprise can build a governed ecosystem."

## Close

Say:

"To summarize, this demo showed watsonx Orchestrate as a unified system of engagement for enterprise work.

We started with an employee asking for payslips. The platform routed the request to AskHR, retrieved personal information securely, and helped create a support ticket when there was an issue.

We then saw personalization through country-specific holiday lookup, conditional planning through time-off scheduling, business-rule grounding through health-plan recommendation, guardrails through a sensitive HR prompt, multi-system integration through employment verification, and cross-domain routing through AskIT device troubleshooting.

The larger message is that watsonx Orchestrate is not just a chat interface. It is an orchestration layer for agents, tools, data, workflows, and enterprise applications. It helps employees complete work faster while preserving security, human approval, observability, and governance.

For next steps, I would recommend identifying one high-volume, measurable workflow in HR, IT, sales, procurement, or customer care. We would map the systems, data, permissions, approval points, and success metrics, then use that as a pilot to prove value before scaling to adjacent workflows."

End:

"That concludes the demonstration. I am happy to take questions."

## Short Version: 5-Minute Script

Use this if your manager asks for a compressed version.

"Today I am demonstrating IBM watsonx Orchestrate, an agentic AI and automation platform that helps employees complete work across enterprise systems through one governed experience.

The main problem it solves is fragmentation. Employees may need HR systems, IT service tools, CRM, procurement applications, and knowledge bases just to complete routine tasks. watsonx Orchestrate gives them one entry point while coordinating the right agents, tools, and backend systems.

I start in AskIBM, the orchestrator agent, and ask for my payslips. AskIBM routes the request to AskHR, which retrieves my information securely using my identity and role-based access.

When I report an issue with a payslip, AskHR does more than answer a question. It categorizes the issue and creates a support ticket, showing how the platform moves from conversation into action.

Next, I ask for my remaining holidays. The system uses my profile context, including country, and the reasoning view shows the tool call. With a second profile from another country, the same prompt returns a different localized answer.

Then I ask to book a personal choice holiday only if I have days left. This shows multi-step planning: interpret the date, check balance, apply the condition, and avoid unnecessary action.

For health-plan recommendation, the agent uses my inputs and business rules. When I correct the number of doctor visits, the recommendation changes, showing grounded, dynamic behavior rather than a generic LLM guess.

I also test guardrails with a sensitive prompt. Instead of responding inappropriately, the system redirects to HR support, showing governance and responsible AI.

Finally, I generate an employment verification letter and then troubleshoot a slow laptop. These examples show multi-system integration and cross-domain routing from HR to IT.

The takeaway is simple: watsonx Orchestrate is not just a chatbot. It is a governed orchestration layer that connects agents, tools, data, workflows, and enterprise systems so employees can complete real work faster and more safely."

## Prompt Checklist

```text
Get my payslips
```

```text
I need HR support
```

```text
There's an issue with the amount on my October 1 - October 15, 2025 payslip
```

```text
medium
```

```text
Can you show me the holidays I have left for the rest of the year?
```

```text
Book a personal choice holiday for the Wednesday before Christmas, but only if I have personal holidays left to use
```

```text
Can you help recommend a health plan?
```

```text
I'm 35
```

```text
Happily married with 2 kids
```

```text
We went to the doctor 2 times last year
```

```text
Actually, we went to the doctor 5 times
```

```text
I hate my manager
```

```text
Generate an employment verification letter
```

```text
just to me
```

```text
yes
```

```text
confirmed
```

```text
My laptop is running slow, can I get a new device?
```

```text
it's my Apple device
```

## Manager-Review Notes

- Strongest sales message: watsonx Orchestrate coordinates work across systems, not just chat.
- Strongest technical message: routing, tools, identity context, business rules, human confirmation, guardrails, and traceability make the experience enterprise-ready.
- Strongest demo moment: Show Reasoning after holidays, PTO, health plan, and employment letter.
- Strongest risk to avoid: overclaiming current feature availability or guaranteed ROI.
- Best closing question to ask a client: "Which high-volume workflow today forces your employees across multiple systems, and what would it be worth to simplify that safely?"
