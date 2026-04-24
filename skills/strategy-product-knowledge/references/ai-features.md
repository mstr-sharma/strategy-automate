# Strategy AI Features Reference

## Overview

Strategy's AI capabilities are collectively marketed as **Auto AI Suite**, rebuilt on an agentic foundation with Auto 2.0. The platform is positioned as an **AI+BI platform** that accelerates AI with BI—combining enterprise BI expertise with modern AI capabilities.

## Brand Positioning

**Tagline:** "Unlock AI-Powered Intelligence Across Your Data Journey"

**Key Message:** "Streamline analytics, reduce manual effort, empower every decision, and future-proof your tech stack with Strategy AI"

**Differentiation:** Strategy brings decades of enterprise BI expertise to AI, ensuring:
- Data accuracy and integrity
- Enterprise-grade governance
- Trusted, explainable results
- No AI hallucinations (grounded in governed data)

## NEW February 2026 — Auto Voice, MCP Mosaic Access, LLM Updates

### Faster, Smarter Auto Voice Experience

Voice is becoming a natural way for executives and frontline teams to access insights. The February 2026 release makes Auto Voice substantially faster and more conversational.

**Key Improvements:**
- **Lower latency** — Responses arrive faster with less perceived wait time
- **Smoother turn-taking** — More natural conversation flow, like speaking to an assistant
- **Natural-sounding fillers** — Reduces robotic feel during multi-step requests
- **Gemini-powered integrations** — Enriched voice interactions via Gemini backend
- **Parallel action execution** — Can retrieve data, run calculations, and summarize results simultaneously for multi-step queries
- **Improved sentence handling** — Clearer, more shareable voice responses

### MCP Direct Mosaic Access (Preview Feature)

*Preview feature:* Users can now access Mosaic models directly in the MCP server—without needing to go through an agent. This allows MCP clients (ChatGPT, Claude, Copilot, etc.) to query the unified semantic layer directly, further lowering the barrier to governed data access.

**See:** [Interact with Agents Using an MCP Server](https://www2.microstrategy.com/producthelp/2021/NextGenAI/en-us/Content/agent_MCPServerIntegration.htm)

### LLM Updates (February 2026)

**BYOE (Bring Your Own Endpoint) for Gemini 2.5:**
- Now available for both **AI Agents** and **Auto Dashboards**
- Customers can bring their own Gemini 2.5 endpoint for greater control over LLM infrastructure

**Open Source LLM Change (Preview):**
- *Preview:* LLAMA LLM is being replaced by a **mixed model** approach using GPT-OSS and **Gemma-27b** as the new go-to open source model
- Applies to both AI Agents and Auto Dashboards



**CRITICAL FEATURE:** Strategy now supports the Model Context Protocol (MCP), enabling true AI freedom and multi-platform agent interaction.

**What is MCP Integration:**
Connect Strategy AI Agents to an MCP server that can be accessed from multiple AI client applications including:
- AWS/Amazon Quick Suite
- ChatGPT
- Copilot Studio
- Claude
- Gemini

**How It Works:**
The MCP server in Strategy Library exposes tools that allow MCP client applications to discover, interact with, and query Strategy AI Agents directly. Users can interact with their Strategy Agents from any MCP-compatible client in a ChatGPT-like interface.

**Key Benefits for AI Freedom Narrative:**
- **No Vendor Lock-in**: Use Strategy Agents from any MCP-compatible AI platform
- **Unified Agent Access**: Access your enterprise agents from the AI tools your team already uses
- **Cross-Platform Flexibility**: Work in ChatGPT, Claude, or Copilot while leveraging Strategy's governed data
- **Enterprise Governance**: Maintain Strategy's data governance even when accessed through external AI tools
- **Container Support**: Enable the MCP server in container-based environments for flexible deployment

**Business Value:**
This represents a paradigm shift in enterprise AI—organizations can now leverage Strategy's governed semantic layer and enterprise-grade AI agents through their preferred AI interfaces, eliminating the need to choose between best-in-class AI tools and enterprise data governance.

## Auto AI Suite Components

### 1. AI Agents (Auto 2.0)

**Overview:**
Customized standalone bots that expand data consumption with conversational analytics.

**Key Capabilities:**
- Create **specialized AI agents** tailored to specific business domains
- **Universal Agent** connects all specialized agents to work together
- Conversational analytics with natural language queries
- Business-ready AI that understands company-specific language
- Customizable branding and personas
- Context-aware answers grounded in governed data

**Technical Details:**
- Built on agentic foundation
- Agents can be embedded across the organization
- Enable datasets for agent use
- Secure deployment within Strategy ecosystem
- No coding or technical expertise required from end users

**NEW January 2026 Capabilities:**

**1. AI-Enabled Data Models as Datasets (Mosaic Integration):**
Select AI-enabled data models created in Mosaic Studio as datasets for agents. The agent interprets questions, detects the relevant Mosaic data model, and responds with answers based on the metrics and relationships defined in that model. This enables:
- Conversational analytics grounded in Mosaic's governed semantic layer
- Unified key driver workflow logic for all agents (including those with Mosaic models)
- Enterprise-grade governance for AI-powered conversations

**NEW February 2026 — Mosaic Model Links in Agents:**
Agents can now use Mosaic model links directly. This extends the Jan 2026 Mosaic integration so that linked/cross-model relationships are fully available within agent conversations, enabling richer, multi-model analytical queries through the conversational interface.

**2. Enhanced Key Driver Analysis (KDA):**
Significant improvements using statistical methods for more accurate insights:
- **Deep workflow optimization** automatically filters for clean and information-rich dimensions
- **Maximum Relevancy and Minimum Redundancy (MRMR)** method to identify the most relevant columns
- Ensures faster and statistically significant results
- Sufficient sample points to accurately reflect population trends
- Statistical graphs generated for each feature to assess relationships with target metrics
- Improved outlier detection

**3. Voice Command Interactions:**
Comprehensive voice interface improvements for accessibility and mobile use:
- Voice command state persistence (remembers enabled/disabled when reopening agent)
- **Immersive mode**: Answers displayed as audio only without on-screen subtitles
- Settings to choose voice, output device, and input device
- **Mobile device support**: Full voice interaction on iOS and Android
- Refined interface and animations for better user experience

**4. SQL Template for Custom Instructions:**
Enable the SQL template to create custom instructions for picking columns when specified conditions are met. This improves on the previous Customer Instruction and column description approach with easier-to-use conditional logic.

**5. Unstructured Data Support:**
Add unstructured data files as data sources and manage them using Strategy Library. Agents can now answer questions about documents, PDFs, text files, and other unstructured content.

**6. Answer Caching:**
User questions and answers are cached for each agent, with ability to manage these caches. Improves response time and reduces compute costs for repeated questions.

**7. Enhanced Deep Research Reports:**
Visual representation of deep research reports has been polished with:
- More concise presentation prioritizing key insights
- PDF exports include functional table of contents with navigation
- Better formatting and readability

**Example Use Cases:**
- Sales team asks questions about pipeline and revenue
- Finance team queries budget vs actual metrics
- Executive team gets instant KPIs through conversational interface
- Domain-specific bots (e.g., "Olympic Knowledge Bot 2.0" for sports analytics)
- Conversational exploration of Mosaic data models
- Voice-based analytics on mobile devices

### 2. Auto Dashboards

**Overview:**
AI-powered dashboard authoring that generates visualizations automatically from data.

**Key Capabilities:**
- **Create a Single Visualization** - Generate individual charts from natural language
- **Create a Page of Visualizations** - Generate entire dashboard page with multiple charts
- **Create a Dashboard Page From an Image** - Upload wireframe/sketch and generate dashboard (colors extracted automatically for custom palettes)
- **Create an entire chapter** of dashboards from your data
- Instant dashboard creation with AI assistance

**NEW January 2026 Enhancements:**

**1. Free-Form Layout:**
Create pages or chapters using free-form layout that independently positions, sizes, and layers containers on a page. This provides complete design flexibility beyond traditional grid-based layouts.

**2. Image-Based Dashboard Creation:**
When you create a dashboard page from an image, Auto now extracts colors from the image to automatically create custom color palettes for the dashboard, ensuring visual consistency with your brand or design.

**3. Rich Text Boxes:**
Create and format rich text boxes within Auto Dashboards for annotations, explanations, and narrative content alongside visualizations.

**4. Regular Dashboard Feature Parity:**
Auto Dashboards now support all regular Strategy dashboard improvements including:
- Iconic KPI visualization (including hiding the image)
- Page level image backgrounds
- Color palettes at the visualization level (box plot, Sankey, histogram, time series)
- Page background customization
- Shadow effects on object containers

**5. Floating Auto Dashboard Panel:**
Display the Auto Dashboard panel as a floating window that can be dragged and resized. This leaves more space for the dashboard canvas and can be minimized to save screen space, then maximized when needed.

**Workflow:**
1. User describes desired analysis, uploads image, or uses natural language
2. Auto analyzes data and requirements
3. Generates appropriate visualizations with auto-generated color schemes (if from image)
4. User can refine, customize, and add rich text annotations as needed

### 3. Auto Answers

**Overview:**
Chatbot automatically integrated into Strategy dashboards for self-service analytics.

**Key Capabilities:**
- Embedded directly in dashboards (no separate interface)
- Ask questions about the data you're viewing
- Get AI-powered explanations of trends and insights
- Extend insights without leaving your workflow
- Self-service analytics for business users

**AI Interpretation Features:**
- Understand what Auto is "seeing" in your data
- Transparent logic and reasoning
- Traceable interactions with underlying data sources

### 4. Auto Expert

**Overview:**
Strategy's customer support chatbot embedded in the Strategy website.

**Key Capabilities:**
- Navigate Strategy documentation
- Troubleshoot technical issues
- Open new support cases
- Review existing support tickets
- On-demand customer assistance

**Access:**
Available through the Strategy website by clicking the Auto Expert icon.

### 5. AI Data Modeling

**Overview:**
AI-powered capabilities within Mosaic Studio for accelerated data model creation.

**Key Capabilities:**
- **10x faster data modeling** with AI assistance
- Auto-creation of data models from source systems
- AI-powered data enrichment and metadata generation
- Automated data cleansing and quality improvements
- Intelligent attribute and hierarchy creation

**Workflow:**
1. Connect to data source
2. AI analyzes schema and relationships
3. Suggests model structure and definitions
4. Auto-generates attributes, metrics, and hierarchies
5. User reviews and refines

### 6. AI Storytelling

**Overview:**
AI-generated narrative insights that explain what's happening in your data.

**Key Capabilities:**
- Automatically identify trends and anomalies
- Generate natural language explanations
- Highlight important insights users might miss
- Provide context for data changes

### 7. AI Insights

**Overview:**
Proactive AI-powered intelligence delivered within dashboards and reports.

**Key Capabilities:**
- Surface hidden patterns in data
- Predictive analytics and forecasting
- Anomaly detection
- Automated alerts for significant changes

### 8. AI in HyperCards

**Overview:**
AI-powered intelligence cards that inject insights into any web application.

**Key Capabilities:**
- Contextual AI insights overlaid on web applications
- No-code deployment
- Enterprise intelligence in the apps users already use

## Advanced AI Features

### Knowledge Assets
- Build reusable knowledge bases for AI agents
- Store domain-specific information
- Improve accuracy with curated content

### AI Interpretation
- Understand how AI arrives at conclusions
- Transparent reasoning and logic
- View underlying calculations and data sources

### Forecasting
- Time-series prediction
- Trend analysis
- What-if scenario modeling

## Technical Architecture

### LLM Integration

**Supported LLM Models (Updated February 2026):**

Strategy now supports multiple LLM providers and models:

**For AI Agents:**
- Microsoft Azure OpenAI (original provider)
- **Gemini-2.5-flash** (Jan 2026)
- **Gemini-embedding-001** (Jan 2026)
- **BYOE for Gemini 2.5** (NEW - Feb 2026)
- **Offline LLM models** (Jan 2026) - Strategy AI works with offline/air-gapped LLM models for secure environments
- *Preview (Feb 2026):* Mixed open-source model — GPT-OSS + **Gemma-27b** (replaces LLAMA)

**For Auto Dashboards:**
- Microsoft Azure OpenAI (original provider)
- **LLAMA 3.3 70B** (Jan 2026) — Including auto narratives and auto answers
- **Gemini-2.5-flash** (Jan 2026) — Including auto narratives and auto answers
- **BYOE for Gemini 2.5** (NEW - Feb 2026)
- **Offline LLM models** (Jan 2026)
- *Preview (Feb 2026):* Mixed open-source model — GPT-OSS + **Gemma-27b** (replaces LLAMA)

**For Mosaic Studio:**
- **Gemini-2.5-flash** (Jan 2026) — For AI-powered data modeling
- **Offline LLM models** (Jan 2026)

**Model Management:**
- Model selection managed by Strategy based on optimal performance for each use case
- **MCP Integration** enables use of Strategy Agents through external AI platforms (ChatGPT, Claude, Copilot, etc.) while maintaining Strategy's data governance

### Data Security and Privacy
- All interactions within secure Strategy platform boundaries
- **No external data transmission** - sensitive data never leaves platform
- **No data retention** by external AI services
- Configurations prevent data storage by LLM provider
- Enterprise-grade security and compliance

### Data Grounding
- All AI responses **grounded in governed data** from Mosaic/Strategy One
- Eliminates hallucinations through semantic layer integration
- **Traceable interactions** with underlying logic and data sources
- Lineage tracking for audit and compliance

## Key Benefits

### 1. Deliver Analytics at Scale
- Support every use case from reports to mobile apps to AI bots
- Scale customizable, domain-aware, secure insights across business functions
- Embed Auto on web, mobile, and apps for AI anywhere
- User-friendly interface empowers adoption at scale

### 2. Simplify Costs and Governance
- **Grounded in governed data** to eliminate hallucinations and guesswork
- **Traceable interactions** with underlying logic, lineage, and data sources
- **Centralized control** to manage and lower total cost of AI ownership
- Simple seat-based pricing

### 3. Adapt with Agility
- Modern, open architecture with 100+ connectors
- APIs and cloud-native support across all major platforms
- Deliver AI-powered analytics everywhere via open API
- Accelerate data modeling up to 10x with AI in Mosaic Studio
- Integrate feedback, usage logs, and training data without disrupting users

## Deployment and Availability

- **Infrastructure:** Cloud only (not available on-premises)
- **Trial:** 30-day free trial available
- **Licensing:** Included with Strategy One subscriptions (varies by tier)

## Customer Use Cases and Quotes

### Retail (GUESS)
*"[Strategy AI] brings down the last remaining barrier that our end users have to their data. Instead of having to run a report, use an application, we can bring it down so that they can just ask questions from a personal level."*
- Bruce Yen, VP of Retail Applications

### Retail (The Warehouse Group)
*"We use Strategy AI to accelerate decision making. It empowers people who don't know how best to use our reporting tools to quickly get the key answers they need."*
- Keryn McKenzie, Chapter Area Lead, Data, Insights & Services

### Life Sciences (Bayer)
*"We believe Strategy AI will have a significant impact at Bayer by giving our users automated, conversational insights about our critical data."*
- Mathew Ratnam, Director and Digital Lead, Data & Analytics

## FAQs

**Q: What is Auto?**
Auto is Strategy's virtual AI assistant that helps users analyze data through natural language in an intuitive chatbot interface. With a suite of AI features, Auto is seamlessly integrated throughout the platform.

**Q: What makes Strategy One an AI+BI platform?**
Strategy accelerates AI with BI. As the market leader in Enterprise BI, Strategy has supported the world's most innovative companies with large-scale analytics applications, ensuring data accuracy, integrity, and governance on a global level. This same rigor is applied to AI products.

**Q: Can I use Strategy Agents with other AI platforms like ChatGPT or Claude?**
Yes! As of January 2026, Strategy supports the Model Context Protocol (MCP), enabling you to interact with your Strategy AI Agents from any MCP-compatible client including ChatGPT, Claude, Copilot Studio, Gemini, and AWS/Amazon Quick Suite. This gives you the freedom to use your preferred AI interface while maintaining Strategy's enterprise-grade data governance.

**Q: What LLM models does Strategy support?**
Strategy now supports multiple LLM providers including Microsoft Azure OpenAI, Google Gemini models (Gemini-2.5-flash, Gemini-embedding-001), BYOE for Gemini 2.5 (Feb 2026), LLAMA 3.3 70B, and offline LLM models for air-gapped environments. A preview mixed open-source model (GPT-OSS + Gemma-27b) is being introduced as the new open source default in February 2026. Model selection is optimized by Strategy for each use case (Agents, Auto Dashboards, Mosaic Studio).

**Q: How does Auto safeguard my data?**
All interactions take place within the secure boundaries of the Strategy platform. No sensitive or personal data is transmitted or stored externally. Configurations strictly prevent data retention or usage by the LLM provider. Even when accessing Strategy Agents through external MCP clients (like ChatGPT), the data governance and security remain controlled by Strategy.

## Industry-Specific AI Applications

Strategy AI is being used across industries:
- **Financial Services** - Risk assessment, fraud detection, client insights, regulatory compliance
- **Healthcare** - Patient analytics, operational efficiency, clinical insights
- **Retail** - Customer behavior analysis, inventory optimization, demand forecasting
- **Public Sector** - Citizen services, operational efficiency, data-driven policy making
- **Insurance** - Claims processing, risk assessment, underwriting automation
- **Life Sciences** - Research analytics, clinical trial insights, regulatory reporting
- **Manufacturing** - Predictive maintenance, quality control, supply chain optimization
