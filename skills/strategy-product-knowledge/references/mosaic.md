# Strategy Mosaic Reference

## Overview

Strategy Mosaic is Strategy's newest product (launched 2025), positioned as the **Universal Semantic Layer** for the AI era. It provides a unified, trustworthy data foundation essential for successful AI strategies.

## Product Positioning

**Tagline:** "Build an AI-Ready, Trusted Data Foundation for your Enterprise"

**Core Value Proposition:**
- Connect every data silo without the cost and complexity of data warehouses
- Control business definitions centrally
- Consume trusted data in any application
- Ensure data is ready for AI workloads

## Three Core Components

### 1. Universal Semantic Layer

The foundational layer that ensures a single source of truth for enterprise analytics.

**Key Capabilities:**
- **Single Source of Truth** - Ensure consistent intelligence across systems, encapsulating data relationships and metrics
- **Comprehensive Data Definitions** - Provide user-friendly definitions to facilitate advanced analytics without technical skills
- **Robust Security and Governance** - Centralize security for consistent enforcement and access control across systems

**Technical Details:**
- Acts as an abstraction layer between data sources and consumption tools
- Harmonizes data definitions, metrics, and business logic
- Enables governed access to data across the organization

### 2. Mosaic Studio

An AI-powered modeling tool that accelerates data preparation and model creation.

**Key Capabilities:**
- **AI-Powered Model Creation** - Speed up data modeling with AI tools for auto-creation, enrichment, and cleansing
- **Transform raw data into actionable insights** with ease, efficiency, and accuracy
- **Accessible to non-technical users** - Almost anyone can utilize Mosaic Studio's AI functionality
- **Accelerate data modeling up to 10x** with AI assistance
- **AI Assistant for Python Query Data Source (NEW - Jan 2026)** - Use the AI assistant to automatically create Python queries to import data, simplifying technical data integration

**Mosaic Model Linking (NEW - Jan 2026):**
Available out-of-the-box to create and view linked attributes across Mosaic models. Establish relationships between disparate Mosaic models and enrich analytical content using:
- Import existing Mosaic models into your current project
- Model link suggestions powered by AI to identify potential relationships
- View Mosaic model links to understand cross-model dependencies

**Additional Features (Jan 2026):**
- Manage Mosaic models directly in the Sources pane for streamlined workflow
- Support for Gemini-2.5-flash LLM model for enhanced AI capabilities
- Works with offline LLM models for air-gapped or secure environments
- Use time attributes to create time transformation metrics automatically

**NEW February 2026 — BigQuery Service Account Authentication:**
Mosaic Studio now supports connecting to Google BigQuery using service account authentication and vault connections. This enables more secure, credential-managed access to BigQuery data sources without user-level credential sharing.

**Use Cases:**
- Rapidly build data models for business analysis
- Cleanse and structure data without extensive technical skills
- Create attributes and hierarchies automatically
- Enrich data models with AI-generated metadata
- Link multiple Mosaic models together for unified analytics
- Build AI-enabled data models for use with Strategy AI Agents

### 3. Mosaic Sentinel (MAJOR UPDATE - January 2026)

A unified data governance intelligence platform that provides enterprises real-time risk alerts, comprehensive audit visibility, and clear usage insights across their semantic layer without data movement or vendor lock-in.

**Three Core Modules:**

1. **Risk Management**
   - Real-time risk alerts for sensitive data access
   - Intelligent risk detection and scoring
   - Proactive threat identification
   - Security policy enforcement

2. **Audit & Compliance**
   - Comprehensive audit visibility across all data access
   - Complete audit trail for compliance requirements
   - Track who accessed what data and when
   - Support regulatory compliance (GDPR, HIPAA, SOX, etc.)

3. **Usage Insights**
   - Clear visibility into semantic layer utilization
   - Monitor data consumption patterns across the organization
   - Identify most-used models, metrics, and data sources
   - Optimize semantic layer performance based on actual usage

**Key Benefits:**
- End-to-end visibility into sensitive operations, model changes, and overall ecosystem activity
- Complete tracking without data movement (governance without copying data)
- Eliminates vendor lock-in for governance tooling
- Unified platform for all governance needs

## NEW February 2026 — AI Sync for Linked Models

As organizations standardize on a universal semantic layer, keeping AI experiences aligned as models change becomes a key operational challenge. Strategy now addresses this with automated AI synchronization across linked Mosaic models.

**How It Works:**
- Strategy pre-validates publication status across all connected models before enabling AI
- Flags inactive or unpublished elements in real time so issues are surfaced immediately
- Automatically re-enables AI when underlying models are updated—no manual maintenance required

**Key Benefits:**
- Less manual effort to maintain AI experiences across a growing semantic layer
- Fewer broken AI interactions caused by unpublished or inactive model elements
- More consistent, governed AI-driven insights as models evolve
- Scales well for organizations with complex, multi-model semantic layer architectures

### Data Connectivity
- **200+ data sources** supported
- **Optimized Access Connectors** - Enhanced analytics with specialized connectors for:
  - Tableau
  - Power BI (with enhanced DAX support - see below)
  - Excel
  - Google Sheets
  - Database clients
  - ArcGis (NEW - Jan 2026) - Connect ArcGis visualizations to Power BI DAX through Mosaic
- **Open and Flexible Data Access** - Standardized access for third-party workloads

**Power BI Connector Enhancements (Jan 2026):**
- Data format synchronization: When you update the data format while editing a Mosaic model and refresh your data in Power BI, the new data format displays automatically
- Hidden forms support: When you hide or display a form while editing a Mosaic model and refresh your data in Power BI, the form displays correctly in your data
- Language localization: When you define your language in your Strategy environment and refresh your data in Power BI, the default data format updates to match the locale

### Performance
- **Query Acceleration Engine** - Utilize an in-memory engine for:
  - Pushdown processing to data sources
  - Cross-source calculations
  - Intelligent caching

### AI Integration
- AI-powered data model creation and enrichment
- Enables context-rich AI for accurate, explainable enterprise-grade results
- Eliminates AI hallucinations by grounding in governed data

## Why Choose Mosaic

### 1. Data and Security Consistency
Leverage existing data infrastructure to ensure consistent definitions and access controls

### 2. Faster Time to Value
Speed up deployment and insights with AI-powered model creation and standardized data definitions—no need to wait for IT

### 3. Better AI Outcomes
Deliver context-rich AI for accurate, explainable enterprise-grade results

### 4. Lower Cost of Ownership
- Reduce infrastructure costs by eliminating redundant data pipelines
- Leverage existing data infrastructure
- Maximize existing data investments
- Lower cloud query expenses

### 5. Eliminate Vendor Lock-in
Build a vendor-agnostic architecture for seamless movement between tools

## Integration with Strategy Ecosystem

Mosaic works seamlessly with:
- **Strategy One** - The core BI platform leverages Mosaic's semantic layer
- **Auto AI Suite** - AI agents and analytics are powered by Mosaic's governed data layer
  - **AI-Enabled Data Models (NEW - Jan 2026)**: Mosaic models can now serve as datasets for Strategy AI Agents. The agent interprets questions, detects the relevant Mosaic data model, and responds with answers based on the metrics and relationships defined in that model. This deep integration enables conversational analytics grounded in Mosaic's governed semantic layer.
- **Third-party tools** - Tableau, Power BI, ArcGis, and other BI/visualization tools can connect through Mosaic
- **Workstation** - Add Mosaic models as document datasets directly in Strategy Workstation

## Mosaic Demos Available

The product includes demonstrations for:
- Data Connectivity - Connecting to databases and third-party tools
- Auto Attributes & Hierarchies - AI-generated data structures
- Data Cleaning - AI-powered data preparation
- AI-Powered Insights - Delivering intelligent analytics

## Launch Information

- **Unveiled:** World 2025 conference (May 2025)
- **Availability:** Generally Available as of 2025
- **Deployment:** Cloud infrastructure required

## Technical Architecture

Mosaic sits as a middle layer:
```
[Data Sources] → [Mosaic Universal Semantic Layer] → [Consumption Tools]
                         ↓
            [Mosaic Studio (AI Modeling)]
                         ↓
            [Mosaic Sentinel (Governance)]
```

**Data Flow:**
1. Multiple data sources connect to Mosaic
2. Mosaic Studio helps create and maintain unified semantic models
3. Universal Semantic Layer provides consistent definitions
4. Mosaic Sentinel monitors and governs access
5. Any consumption tool (BI, AI, productivity apps) accesses data through Mosaic

## Eight Key Technical Differentiators

The following represent Mosaic's strongest and most defensible competitive advantages. Each is a genuine architectural differentiator with direct impact on deployment outcomes, governance posture, and total cost of ownership. Use these when competing against any semantic layer vendor.

### 01 — Governance: RLS, CLS & Mosaic Sentinel
Enterprise governance requires enforcement that is consistent, automatic, and auditable across every consumer of the semantic layer. Mosaic embeds row-level security (RLS), column-level security (CLS), and role-based access control **directly into the semantic model**, so policies apply uniformly regardless of which BI tool, AI agent, or API queries the data. Users always see the right data; logic is never duplicated in downstream systems.

**The Mosaic advantage:** Mosaic Sentinel adds an intelligence layer on top of access governance — monitoring usage patterns, detecting anomalies, and enabling audit and compliance workflows. Governance in Mosaic is not just enforced, it is **observable and proactive**.

**Key message:** Governance enforced at the semantic layer — not replicated in every downstream tool.

---

### 02 — DAX / XMLA Connectivity for Power BI
Most semantic layer integrations with Power BI rely on SQL-based connectivity, which degrades semantic fidelity — calculation logic, relationships, and metric definitions may not survive the translation. Mosaic provides **native XMLA/DAX connectivity** to Power BI, so reports consume the semantic model with full fidelity, preserving metric definitions, relationships, and business logic exactly as defined.

**The Mosaic advantage:** Native DAX/XMLA connectivity for Power BI is available from only a handful of vendors in the semantic layer market today. This ensures optimal performance and full semantic consistency within Power BI environments without compromise.

**Key message:** Key differentiator for enterprise Power BI deployments — available from very few vendors.

---

### 03 — Dynamic Aggregation & Aggregate Awareness
Serving analytically accurate results at scale requires routing queries to the right level of data granularity — without manual tuning for every aggregation scenario. Mosaic's engine **dynamically determines the optimal aggregation path at query time**, automatically selecting the most efficient level of detail based on the context of each request.

**The Mosaic advantage:** Aggregate awareness removes the need to predefine every aggregation scenario or manually tune query routing. Users model data once; Mosaic's engine adapts intelligently to different analytical use cases, maintaining both correctness and performance across workloads.

**Key message:** Correct and performant by default — without manual aggregation configuration.

---

### 04 — In-Memory Engine: Cost Control & Performance Optimization
High-concurrency analytical workloads generate significant compute costs when every query hits the underlying warehouse directly. Mosaic includes a **high-performance in-memory engine** that enables selective data acceleration — caching or importing critical datasets to reduce query latency and control compute costs without requiring full data movement or replication.

**The Mosaic advantage:** Customers can strategically accelerate high-frequency workloads, reducing Snowflake, Databricks, or other platform compute costs while maintaining query performance. This hybrid approach — serving some queries from memory, others live — balances performance and cost in a way that warehouse-only solutions cannot replicate.

**Key message:** Addresses both performance and infrastructure cost — not just one or the other.

---

### 05 — Multi-Source Live Federation
Enterprise data is distributed across multiple platforms — cloud warehouses, lakehouses, operational databases, and specialized systems. Mosaic supports **true multi-source live federation**, enabling queries that span heterogeneous data platforms within a single semantic model, without requiring data consolidation or movement into a central store.

**The Mosaic advantage:** Through intelligent pushdown and distributed query planning, Mosaic minimizes data movement while delivering a unified business view across sources including Snowflake, Databricks, and operational databases. Multiple live-connect Mosaic models can be linked to enable live cross-source federation today.

**Key message:** Cross-platform analytics without the cost or latency of data consolidation.

---

### 06 — AI Integration: Mosaic MCP & Agent Platform
AI agents and LLMs that query data warehouses directly lack the business context needed to produce semantically accurate results. Without a governed definition of which "Revenue" calculation is authoritative or what qualifies as an "Active Customer," a model produces results that are computationally valid but **semantically incorrect**. Mosaic exposes governed business semantics to AI systems through Mosaic MCP and the Strategy Agent platform.

**The Mosaic advantage:** AI agents using Mosaic MCP operate on governed entities, authoritative metrics, and defined relationships — not raw SQL or unstructured data. This significantly improves accuracy and explainability, positioning Mosaic as the foundation for intelligent automation and decision support.

**Key message:** Semantic foundation for governed, explainable AI — not just natural-language-to-SQL.

---

### 07 — Rich Semantics: Level Metrics, Conditional Logic & More
Many semantic layer tools focus primarily on simple metric definitions — a calculation tied to a column. Mosaic's semantic model is significantly more expressive: supporting **level-aware metrics** that behave correctly across different hierarchy levels, **conditional metrics** that apply business logic based on contextual rules, and flexible expression-based attribute forms that enable precise representation of complex business concepts.

**The Mosaic advantage:** Level metrics, conditional metrics, and expression-based attribute forms allow complex business logic to be modeled once and reused consistently across all consuming tools. Compared to vendors focused primarily on simple metric layers, Mosaic delivers a much richer and more precise representation of business meaning.

**Key message:** Richer semantic modeling than any direct competitor in the category.

---

### 08 — Platform Extensibility: SDK & Transaction Services
Most semantic layer tools are designed for analytics consumption — read-only queries delivered to BI tools and agents. Strategy's platform extends beyond analytics through **robust SDKs and transaction services** that enable customers to build fully customized applications on the semantic layer, operationalizing data into workflows, write-back actions, and live business processes.

**The Mosaic advantage:** Customers including Freddie Mac and Reynolds American — among Strategy's largest SDK users — have built fully customized operational applications on the platform. As Mosaic evolves toward ontology and AI-driven use cases, this extensibility positions the platform as a true business operations layer, not just a semantic layer.

**Key message:** Beyond analytics — a foundation for business operations applications.

---

## Positioning vs Competitors

Mosaic differentiates from traditional semantic layers and data warehouses on eight dimensions. Use the technical differentiators section above for deep competitive conversations. The table below provides quick orientation:

| Competitor type | Key Mosaic advantages |
|---|---|
| **Data Warehouses** (Snowflake, Databricks) | No need to replicate data; works with data where it lives; in-memory engine reduces warehouse compute costs; multi-source federation without data movement |
| **Traditional Semantic Layers** (SSAS, OLAP cubes) | AI-powered modeling (10x faster); vendor-agnostic; native DAX/XMLA for Power BI; rich semantics (level metrics, conditional logic) |
| **Simple Metric Layers** (dbt Semantic Layer, Cube) | Far richer semantic modeling; RLS/CLS enforcement; Mosaic Sentinel governance; SDK extensibility for operational apps |
| **Looker / LookML** | No proprietary language lock-in; works across multiple BI tools simultaneously; AI-powered with governed agent support; dynamic aggregation |
| **Power BI Premium / SSAS** | Native DAX/XMLA fidelity + multi-tool coverage; governed AI agents; cross-source federation without Microsoft lock-in |
| **Data Integration Tools** (Informatica, Fivetran) | Focus on semantic consistency and governance, not just data movement; eliminates need to copy data |

**Strongest differentiators to lead with in competitive displacement:**
- Governance that is observable and proactive (Sentinel), not just enforced
- Native DAX/XMLA for Power BI — only a handful of vendors offer this
- Rich semantics (level metrics, conditional logic) vs. simple metric definitions competitors offer
- AI agents grounded in governed semantics — not just NL-to-SQL
- Hybrid in-memory engine that controls both cost and performance simultaneously

## Common Use Cases

1. **Multi-BI Tool Environments** - Organizations using Tableau, Power BI, and other tools want consistent metrics without rebuilding logic in every tool
2. **AI Readiness** - Companies preparing governed data for AI/ML workloads; AI agents need authoritative business definitions, not raw SQL
3. **Data Modernization** - Legacy BI systems need to modernize without full data migration; preserve existing business logic
4. **Enterprise Power BI Deployments** - Organizations needing full semantic fidelity in Power BI via native DAX/XMLA (not SQL workarounds)
5. **High-Concurrency Cost Control** - Organizations paying high Snowflake/Databricks compute bills can use Mosaic's in-memory engine to reduce query costs selectively
6. **Multi-Platform Federation** - Enterprises with data across Snowflake, Databricks, and operational databases needing a unified semantic view without a central data store
7. **Embedded Analytics** - SaaS companies needing consistent, governed analytics for customers
8. **Regulatory Compliance** - Industries requiring strong data governance, full audit trails, and real-time risk detection (Mosaic Sentinel)
9. **Operational Applications** - Organizations that want to go beyond read-only analytics and build write-back or workflow applications on the semantic layer (SDK extensibility)
