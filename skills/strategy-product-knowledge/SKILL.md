---
name: strategy-product-knowledge
description: Comprehensive knowledge of Strategy Software products with focus on AI and Mosaic features. Use when discussing, explaining, or creating materials about Strategy Software, MicroStrategy, Strategy One, Mosaic, Auto AI Suite, or any Strategy product features. Triggers include questions about Strategy products, creating presentations/proposals about Strategy, competitive positioning, product capabilities, AI+BI platform, semantic layer, embedded analytics, or any Strategy-related content creation.
---

# Strategy Software Product Knowledge

This skill provides comprehensive knowledge of Strategy Software's product portfolio in its current GA state, with particular emphasis on Mosaic and AI capabilities, plus background on core BI products.

## Latest Updates (February 2026 Release)

**MAJOR NEW CAPABILITIES:**

### Mosaic: AI Sync for Linked Models
Strategy now pre-validates publication status across connected Mosaic models, flags inactive or unpublished elements in real time, and automatically re-enables AI when underlying models are updated. This keeps AI experiences aligned as the semantic layer evolves—less manual maintenance, fewer broken experiences.

### Auto Voice: Faster, More Conversational
Auto Voice now responds with lower latency and smoother turn-taking, with more natural-sounding fillers and new Gemini-powered integrations. It can run multiple actions in parallel (retrieve data, run calculations, summarize results), reducing time to insight for multi-step requests.

### MCP Direct Mosaic Access (Preview)
*Preview feature:* Access Mosaic models directly in the MCP server—ask questions against the unified semantic layer without needing to go through an agent first.

### LLM Updates
- BYOE (Bring Your Own Endpoint) support for **Gemini 2.5** for both AI Agents and Auto Dashboards
- *Preview:* LLAMA replaced by a mixed model using GPT-OSS and Gemma-27b as the new open source default

### Dashboard & BI Improvements
- Dynamic date filters (MTD, QTD, YTD) in both authoring and consumption modes
- Table of Contents can now display horizontally at top or bottom in Library Web
- Visualization maximize now fills the full dashboard (not just the panel)
- Contextual object-level links on visualizations and datasets
- Improved modern grid performance (Library and Workstation)

### Subscription Delivery & Security
- **SSH key-based authentication** for SFTP subscriptions (replaces password-based login)
- **Email failure notifications** — owners and recipients are alerted when a scheduled subscription fails to deliver
- Support for setting multiple schedules on a single subscription

### Workstation & Admin
- MDX intelligent cube creation in Workstation (supports SSAS, SAP BW)
- SCIM 2.0 protocol support for system prompt synchronization
- Job Prioritization now includes PowerPoint, Excel, Tableau, Google Sheets, Hyper, and Mosaic types
- Migration setting to use last-modified timestamp rather than migration time
- Enhanced Microsoft Analysis Services (MSAS) security enabled out-of-the-box

### Mosaic Studio
- Google BigQuery now supports service account authentication and vault connections

### Managed Cloud
- Cloud-native backup and restore for Amazon Web Services added to Strategy Managed Cloud Enterprise

**See reference files for complete details on all February 2026 enhancements.**

---

## Previous Release: January 2026

### AI Freedom: Model Context Protocol (MCP) Support
Strategy now supports the Model Context Protocol, enabling true AI freedom. Users can interact with Strategy AI Agents from any MCP-compatible platform including ChatGPT, Claude, Copilot Studio, Gemini, and AWS/Amazon Quick Suite.

### Mosaic Sentinel: Unified Data Governance Platform
Mosaic Sentinel expanded with three core modules (Risk Management, Audit & Compliance, Usage Insights) providing comprehensive real-time governance intelligence across the semantic layer without data movement or vendor lock-in.

### Deep Mosaic + AI Integration
- AI-enabled Mosaic data models can now serve as datasets for Strategy AI Agents
- Model linking capabilities for connecting disparate Mosaic models
- AI assistant in Mosaic Studio for Python query generation
- Expanded LLM support (Gemini-2.5-flash, LLAMA 3.3 70B, offline models)

### Enhanced AI Agent Capabilities
- Statistical Key Driver Analysis improvements (MRMR methodology)
- Comprehensive voice command interactions with mobile support
- Unstructured data file support
- Answer caching for improved performance
- SQL template for custom instructions

## Company Overview

**Strategy Software** (formerly MicroStrategy, rebranded in 2025) is an enterprise AI+BI analytics platform provider. The company positions itself around the tagline "AI+BI Platform for Enterprises."

**Key Company Facts:**
- Rebranded from MicroStrategy to Strategy in 2025
- Founded 1989, headquartered in Tysons Corner, Virginia
- Publicly traded (Nasdaq)
- Annual user conference: Strategy World (Feb 23-26, 2026)

## Product Portfolio

Strategy's product portfolio consists of three main offerings:

### 1. Strategy Mosaic (NEW - Launched 2025)
**Positioning:** Universal Semantic Layer for the AI Era

**For detailed Mosaic information, read:** `references/mosaic.md`

**Quick Summary:**
- Universal Semantic Layer - Single source of truth for enterprise analytics
- Mosaic Studio - AI-powered data modeling tool (10x faster modeling)
  - AI assistant for Python queries, model linking, Gemini-2.5-flash support
  - **NEW (Feb 2026):** Google BigQuery service account authentication & vault connections
- Mosaic Sentinel - Unified data governance intelligence platform
  - Three modules (Risk Management, Audit & Compliance, Usage Insights)
- **NEW (Feb 2026):** AI auto-syncs across linked models — pre-validates, flags inactive elements, re-enables automatically
- Connects 200+ data sources (including ArcGis to Power BI DAX)
- Eliminates vendor lock-in
- Enables AI-ready data foundation
- AI-enabled models serve as datasets for Strategy AI Agents

**Eight Key Technical Differentiators (for competitive conversations):**
See `references/mosaic.md` → "Eight Key Technical Differentiators" section for full detail. Quick reference:
1. **Governance (RLS/CLS + Sentinel)** — enforced at semantic layer, observable via Sentinel — not replicated downstream
2. **Native DAX/XMLA for Power BI** — full semantic fidelity; available from very few vendors
3. **Dynamic aggregation & aggregate awareness** — correct and performant by default without manual tuning
4. **In-memory engine** — selectively reduces Snowflake/Databricks compute costs while maintaining performance
5. **Multi-source live federation** — unified business view across heterogeneous platforms without data movement
6. **AI / MCP integration** — agents operate on governed semantics, not raw SQL or unstructured data
7. **Rich semantics** — level metrics, conditional metrics, expression-based attributes; richer than any direct competitor
8. **SDK & transaction services** — beyond read-only analytics into operational applications (Freddie Mac, Reynolds American)

### 2. Auto AI Suite
**Positioning:** AI-Powered Intelligence Across Your Data Journey

**For detailed AI features, read:** `references/ai-features.md`

**Quick Summary:**
- **Model Context Protocol (MCP) Support (Jan 2026)** - Use Strategy Agents from ChatGPT, Claude, Copilot, Gemini, AWS—TRUE AI FREEDOM
  - **NEW (Feb 2026 Preview):** Direct Mosaic model access via MCP — no agent required
- AI Agents (Auto 2.0) - Customized conversational analytics bots
  - Mosaic model integration, enhanced Key Driver Analysis, voice commands, unstructured data support, answer caching
  - **NEW (Feb 2026):** BYOE for Gemini 2.5; Mosaic model links usable in agents
  - **NEW (Feb 2026):** Auto Voice — lower latency, parallel actions, Gemini-powered, smoother turn-taking
- Auto Dashboards - AI-generated visualizations
  - Free-form layouts, image-based creation with color extraction, rich text boxes, floating panel
  - **NEW (Feb 2026):** BYOE for Gemini 2.5
- Auto Answers - Chatbot integrated in dashboards
- Auto Expert - Customer support chatbot
- AI Data Modeling - 10x faster with AI assistance
- **LLM Support:** Azure OpenAI, Gemini 2.5 (BYOE), LLAMA 3.3 70B, offline models; Feb 2026 Preview: GPT-OSS + Gemma-27b mixed model
- Grounded in governed data to eliminate hallucinations

### 3. Strategy One
**Positioning:** The All-in-One AI+BI Platform (Core BI Platform)

**For detailed Strategy One information, read:** `references/strategy-one.md`

**Quick Summary:**
- Cloud-Native and on-premises deployment
- Enterprise Reporting - Pixel-perfect, high-volume reports
  - **NEW (Feb 2026):** Report creation from intelligent cubes; improved modern grid performance
- Interactive Dashboards - AI-powered creation
  - **NEW (Feb 2026):** Dynamic date filters (MTD/QTD/YTD), horizontal Table of Contents, full-dashboard visualization maximize, contextual object links, improved grid performance
- HyperIntelligence - Inject analytics into any web app (zero code)
- Mobile Analytics - Native iOS/Android apps
- Embedded Analytics - White-label for SaaS/product companies
- Semantic Layer - Unified business logic
- 100+ Data Connectors
  - **NEW (Feb 2026):** BigQuery service account authentication via Mosaic Studio
- Workstation (admin/developer tool) and Library (end-user interface)
  - **NEW (Feb 2026):** MDX intelligent cube creation, SCIM 2.0 support, SSH key-based SFTP auth, email delivery failure notifications, multi-schedule subscriptions

## When to Use This Skill

This skill should be invoked when the user:
- Asks about Strategy, MicroStrategy, or any Strategy Software products
- Needs to create presentations, proposals, or materials about Strategy
- Wants to understand product capabilities or features
- Requests competitive positioning or comparisons
- Discusses AI+BI platforms, semantic layers, or enterprise analytics
- Mentions Mosaic, Auto, HyperIntelligence, or specific product names
- Needs customer-facing content about Strategy products

## How to Use Reference Files

The skill includes three comprehensive reference files:

1. **`references/mosaic.md`** - Read when discussing:
   - Universal Semantic Layer
   - Mosaic Studio, Mosaic Sentinel
   - Data foundation for AI
   - Data connectivity and integration
   - Semantic layer architecture

2. **`references/ai-features.md`** - Read when discussing:
   - **Model Context Protocol (MCP) integration - AI FREEDOM** (Jan 2026)
   - Auto AI Suite capabilities
   - AI Agents, Auto Dashboards, Auto Answers
   - Conversational analytics
   - AI-powered modeling
   - Mosaic + AI Agent integration (Jan 2026)
   - Enhanced Key Driver Analysis and voice commands (Jan 2026)
   - LLM integration (expanded model support including Gemini, LLAMA)
   - AI+BI positioning

3. **`references/strategy-one.md`** - Read when discussing:
   - Core BI platform capabilities
   - Enterprise Reporting
   - Dashboards and visualizations
   - HyperIntelligence
   - Mobile analytics
   - Embedded analytics
   - Semantic layer (BI perspective)
   - Platform architecture
   - Competitive positioning
   - Industry solutions

**Best Practice:** For comprehensive questions, read multiple reference files to provide complete context.

## Key Messaging and Positioning

### Overall Company Positioning
"Strategy Software provides an AI+BI Platform for Enterprises that accelerates AI with BI—combining decades of enterprise BI expertise with modern AI capabilities to deliver trusted, governed, accurate analytics."

### Mosaic Positioning
"Strategy Mosaic is the Universal Semantic Layer that builds an AI-ready, trusted data foundation for your enterprise. Connect every data silo, control your business definitions, and consume trusted data in any application—without the cost and complexity of data warehouses. With Mosaic Sentinel, gain unified governance intelligence with real-time risk alerts, comprehensive audit visibility, and clear usage insights—all without data movement or vendor lock-in."

### AI Positioning
"Strategy brings BI rigor to AI. As the market leader in Enterprise BI, we've supported the world's most innovative companies with large-scale analytics applications. This requires dedication to data accuracy, integrity, and governance on a global level. We apply the same care to our AI products, ensuring you can always trust the results."

### Strategy One Positioning
"Strategy One is the all-in-one AI+BI platform that turns complex data into confident decisions with a unified semantic layer, AI-powered analytics, and full freedom from vendor lock-in—all on a modern, cloud-native platform."

## Common Use Cases

### For Presentations
When creating Strategy presentations:
- Emphasize the AI+BI integration (not just BI, not just AI)
- Highlight Mosaic as the foundation (NEW product, differentiator)
- Showcase Auto AI Suite for modern conversational analytics
- Position Strategy One as the comprehensive platform
- Use customer quotes and industry examples from reference files

### For Product Explanations
When explaining products:
- Start with the business problem being solved
- Explain how the product addresses the problem
- Provide specific capabilities and features
- Include relevant customer examples
- Reference competitive advantages

### For Competitive Positioning
When comparing to competitors:
- Strategy vs Power BI: Better governance, mobile, semantic layer, flexibility
- Strategy vs Tableau: Unified platform, better reporting, stronger governance
- Strategy vs Legacy BI (Cognos, BOBJ): Modern architecture, better UX, AI integration
- Strategy vs Modern BI (Looker, Thoughtspot): More comprehensive, enterprise scale

## Target Audiences

- **Internal Strategy Employees** - Creating internal materials, training, planning
- **Sales and Customer Success** - Customer-facing conversations, demos, proposals
- **Data Leaders** - Understanding AI strategies for data organizations
- **IT Leaders** - Evaluating platform architecture and governance
- **Product Leaders** - Considering embedded analytics
- **Business Leaders** - Understanding enterprise analytics capabilities

## Important Notes

- **Current Release: February 2026** — Theme: Trusted AI experiences, faster voice, reliable delivery
- **MCP Support = AI Freedom (Jan 2026)** - Strategy Agents accessible from ChatGPT, Claude, Copilot, Gemini—eliminates vendor lock-in while maintaining enterprise governance
- **MCP Direct Mosaic Access (Feb 2026 Preview)** - Query the semantic layer directly via MCP without going through an agent
- **Auto Voice upgraded (Feb 2026)** - Lower latency, parallel actions, Gemini-powered, smoother turn-taking
- **AI Sync for Linked Models (Feb 2026)** - AI auto-maintains across linked Mosaic models; pre-validates and re-enables automatically
- **Subscription reliability (Feb 2026)** - SSH key SFTP auth + email failure notifications
- **Always emphasize AI+BI integration** - This is Strategy's key differentiator
- **Mosaic Sentinel is a major governance platform (Jan 2026)** - Unified governance intelligence with Risk Management, Audit & Compliance, and Usage Insights modules
- **Mosaic + AI Deep Integration (Jan 2026)** - Mosaic models now serve as datasets for AI Agents
- **Mosaic is NEW (2025)** - Highlight its newness and innovation
- **Governance is critical** - Strategy's AI is grounded in governed data
- **Company rebranded in 2025** - MicroStrategy is now Strategy Software
- **Cloud-first but hybrid available** - Modern cloud-native with on-premises options for legacy customers

## Quick Reference: Product Hierarchy

```
Strategy Software (Company)
├── Strategy Mosaic (Universal Semantic Layer - NEW 2025)
│   ├── Universal Semantic Layer
│   ├── Mosaic Studio (AI modeling)
│   └── Mosaic Sentinel (governance)
├── Auto AI Suite (AI Features)
│   ├── AI Agents (Auto 2.0)
│   ├── Auto Dashboards
│   ├── Auto Answers
│   ├── Auto Expert
│   └── AI Data Modeling
└── Strategy One (Core BI Platform)
    ├── Cloud & Architecture
    ├── Enterprise Reporting
    ├── Interactive Dashboards
    ├── HyperIntelligence
    ├── Mobile Analytics
    ├── Embedded Analytics
    ├── Semantic Layer
    ├── Data Connectors
    ├── Workstation (admin tool)
    └── Library (user interface)
```
