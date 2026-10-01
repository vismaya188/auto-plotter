# Prompt to Plot — Project Documentation

## 1. Project Overview

**Prompt to Plot** is an AI-powered agent designed to convert natural-language business questions into meaningful Power BI visualizations and actionable insights.

Instead of requiring users to manually understand the dataset, identify relevant metrics, write queries, select chart types, configure Power BI visuals, and interpret the results, Prompt to Plot automates this workflow through a simple conversational prompt.

### Elevator Pitch

> Prompt to Plot transforms natural-language prompts into meaningful Power BI visuals, automatically selecting the right charts, metrics, and insights from the underlying data. It is designed for business analysts, data analysts, developers, and business users who want to turn data into actionable insights quickly, with minimal manual BI effort.

---

## 2. Problem Statement

Organizations have large amounts of business data, but converting that data into useful insights often requires multiple manual steps and specialized BI knowledge.

A typical user may need to:

1. Understand the structure of the available data.
2. Identify which tables and columns are relevant.
3. Determine the appropriate business metrics.
4. Formulate a data query.
5. Decide which visualization best represents the result.
6. Configure the visualization in Power BI.
7. Analyze the output.
8. Extract meaningful and actionable insights.

This process can be time-consuming, repetitive, and difficult for users who do not have advanced Power BI or data-analysis skills.

### The problem Prompt to Plot addresses

**How can a user move from a business question expressed in natural language to an appropriate Power BI visualization and actionable insight with minimal manual BI effort?**

Prompt to Plot addresses this by introducing an AI agent that understands the user's intent, works with the underlying data, selects appropriate metrics and visualizations, and presents the result in a business-friendly way.

---

## 3. Why This Problem Is Important

The value of business data depends on how quickly and accurately users can understand it.

Manual BI workflows can create several challenges:

- **Time consumption:** Building reports and visuals manually can take significant time.
- **Technical dependency:** Users may need knowledge of Power BI, data modeling, DAX, SQL, or visualization techniques.
- **Repetitive work:** Analysts often perform similar visualization and reporting tasks repeatedly.
- **Visualization selection:** Choosing the most suitable chart for a business question is not always straightforward.
- **Delayed decision-making:** Time spent preparing analysis can delay business decisions.
- **Accessibility:** Non-technical users may find traditional BI tools difficult to use independently.

Prompt to Plot aims to reduce these barriers and make data exploration more natural and accessible.

---

## 4. Proposed Solution

Prompt to Plot provides a natural-language interface for interacting with business data.

A user can ask a question such as:

> "Show monthly sales performance for this year and highlight the months with the highest growth."

Instead of manually creating the report, the agent can:

1. Understand the intent of the request.
2. Identify the relevant business entities and metrics.
3. Determine the required data.
4. Generate or execute the appropriate data query.
5. Select an appropriate Power BI visualization.
6. Generate the visualization.
7. Analyze the resulting data.
8. Explain the key findings.
9. Provide actionable insights where appropriate.

The overall objective is to turn **business questions into BI outcomes** with minimal manual intervention.

---

## 5. Target Users

Prompt to Plot is designed for multiple categories of users.

### 5.1 Business Analysts

Business analysts can quickly convert business questions into visualizations without manually configuring every Power BI component.

**Benefits:**
- Faster exploratory analysis.
- Less repetitive visualization work.
- Faster preparation of business reports.
- Easier identification of trends and anomalies.

### 5.2 Data Analysts

Data analysts can use the agent to automate common visualization and exploratory-analysis tasks.

**Benefits:**
- Reduced repetitive work.
- Faster data exploration.
- More time for advanced analysis.
- Consistent visualization recommendations.

### 5.3 Developers

Developers can use the architecture as a foundation for building AI-assisted BI workflows and integrating natural-language interfaces with Power BI.

**Benefits:**
- Simplified BI automation.
- Reusable agent architecture.
- Reduced manual interaction with reporting workflows.

### 5.4 Business Users

Non-technical users can interact with data using natural language rather than learning complex BI interfaces.

**Benefits:**
- Lower learning curve.
- Easier access to data.
- Faster answers to business questions.
- Better data-driven decision-making.

---

## 6. Expected Value and Outcomes

Prompt to Plot is expected to deliver value in four major areas.

### 6.1 Productivity

The solution reduces the number of manual steps required to create visualizations and derive insights.

### 6.2 Faster Decision-Making

Users can move from a question to an understandable visual and insight more quickly.

### 6.3 Reduced Technical Dependency

Users do not necessarily need advanced knowledge of Power BI visualization configuration to begin exploring their data.

### 6.4 Better Accessibility to Data

Natural-language interaction makes BI capabilities more accessible to technical and non-technical users.

### Expected outcomes

- Reduced manual BI effort.
- Faster visualization creation.
- Faster exploratory analysis.
- Improved user productivity.
- Easier access to business insights.
- Improved data-driven decision-making.
- Reduced dependency on specialized BI skills for routine tasks.

---

# 7. High-Level Architecture

The planned architecture can be divided into the following logical layers:

```text
+---------------------------+
|       User / Business     |
|     Natural Language      |
|          Prompt           |
+-------------+-------------+
              |
              v
+---------------------------+
|   Natural Language Input  |
|        & Validation       |
+-------------+-------------+
              |
              v
+---------------------------+
|       AI Agent /          |
|     Orchestration Layer   |
+-------------+-------------+
              |
       +------+------+
       |             |
       v             v
+-------------+  +----------------+
| Data &      |  | Visualization  |
| Semantic    |  | Selection      |
| Understanding| | Logic          |
+------+------+  +-------+--------+
       |                 |
       +--------+--------+
                |
                v
+---------------------------+
|       Query / Data        |
|        Retrieval         |
+-------------+-------------+
              |
              v
+---------------------------+
|      Power BI Layer       |
|  Visual / Report Output  |
+-------------+-------------+
              |
              v
+---------------------------+
|   Insight Generation &    |
|     Recommendations      |
+-------------+-------------+
              |
              v
+---------------------------+
|      User-Friendly        |
|    Visual + Explanation   |
+---------------------------+
```

---

# 8. End-to-End Workflow

The core workflow is:

**Natural-Language Prompt → Intent Understanding → Data/Metric Identification → Query Generation → Visualization Selection → Power BI Visual → Insight Generation**

Each stage is explained below.

## Step 1: User Provides a Prompt

The user enters a business question in natural language.

Example:

> "What were our top five products by revenue last quarter?"

The user does not need to specify the database table, SQL query, DAX expression, or chart type.

---

## Step 2: Intent Understanding

The AI agent interprets what the user is asking.

For the example above, the agent may identify:

- **Business objective:** Find top-performing products.
- **Metric:** Revenue.
- **Dimension:** Product.
- **Time period:** Last quarter.
- **Ranking:** Top 5.
- **Likely visualization:** Bar/column chart.

The agent should distinguish between the user's business intent and the technical implementation required to answer it.

---

## Step 3: Data and Metric Identification

The agent maps the natural-language terms to available data.

For example:

```text
User term: Revenue
Possible data field: Sales[Revenue]

User term: Product
Possible data field: Product[ProductName]

User term: Last quarter
Possible filter: Date/Calendar table
```

A semantic layer or metadata catalog can help the agent understand:

- Tables.
- Columns.
- Relationships.
- Measures.
- Data types.
- Business definitions.
- Available metrics.

This mapping is important because business users may use terminology that differs from the physical database schema.

---

## Step 4: Query Generation

Once the intent and required fields are identified, the agent generates the appropriate query or analytical request.

Depending on the implementation, this may involve:

- SQL.
- DAX.
- Power BI semantic model queries.
- APIs or other supported query mechanisms.

The generated query should be validated before execution.

### Example conceptual query

```text
SELECT TOP 5
    Product,
    SUM(Revenue) AS TotalRevenue
FROM Sales
WHERE Date is within Last Quarter
GROUP BY Product
ORDER BY TotalRevenue DESC
```

The exact implementation can vary depending on the selected data architecture.

---

# 9. Visualization Selection

One of the key capabilities of Prompt to Plot is automatically selecting a visualization based on the user's intent and the structure of the result.

The agent should consider:

- Number of dimensions.
- Number of measures.
- Data types.
- Time-series characteristics.
- Ranking requirements.
- Comparison requirements.
- Distribution.
- Correlation.
- Geographic information.
- User intent.

### Example mapping

| Analytical Requirement | Possible Visualization |
|---|---|
| Trend over time | Line chart |
| Compare categories | Bar/column chart |
| Part-to-whole | Donut/pie chart where appropriate |
| Geographic analysis | Map |
| Relationship between two measures | Scatter chart |
| KPI / single metric | Card |
| Multiple KPIs | KPI/card layout |
| Detailed multidimensional analysis | Table/matrix |
| Ranking | Bar chart |
| Distribution | Histogram |

The goal is not simply to generate a chart, but to select a visualization that communicates the answer effectively.

---

# 10. Power BI Visualization Layer

After the agent determines the appropriate visual and data configuration, the result is delivered through the Power BI layer.

The visualization may contain:

- Selected dimensions.
- Selected measures.
- Filters.
- Sorting.
- Time ranges.
- Aggregations.
- Titles.
- Labels.
- Supporting context.

The exact Power BI implementation can depend on the available Power BI APIs, semantic model, embedding approach, and project environment.

The key architectural principle is:

> The AI agent decides what should be visualized; Power BI provides the BI visualization and reporting environment.

---

# 11. Insight Generation

Generating a chart alone is not enough.

Prompt to Plot also aims to explain what the visual means.

For example, if the generated chart shows monthly revenue:

```text
Monthly Revenue
Jan  → ₹10L
Feb  → ₹12L
Mar  → ₹15L
Apr  → ₹11L
```

The agent could identify:

- Revenue increased from January to March.
- March was the strongest month in the displayed period.
- Revenue declined in April.
- The March-to-April decline may require investigation.

The insights should be grounded in the retrieved data rather than being unsupported assumptions.

---

# 12. Actionable Recommendations

Where appropriate, Prompt to Plot can move beyond descriptive insights and provide potential actions.

For example:

**Observation:**
> Revenue declined significantly in April.

**Potential action:**
> Investigate April's product, region, customer-segment, and sales-channel performance to identify the primary contributors to the decline.

The system should distinguish between:

- **Fact:** What the data directly shows.
- **Interpretation:** What the pattern may indicate.
- **Recommendation:** What the user could investigate or do next.

This distinction helps prevent the system from presenting assumptions as facts.

---

# 13. Agent Responsibilities

The AI agent is the central orchestration component.

Its responsibilities can include:

1. Understand the natural-language request.
2. Identify user intent.
3. Identify required dimensions and measures.
4. Resolve business terminology against the semantic model.
5. Determine required filters.
6. Generate an appropriate data query.
7. Validate the query.
8. Retrieve relevant data.
9. Determine the most suitable visualization.
10. Configure the visualization.
11. Analyze the result.
12. Generate concise insights.
13. Suggest relevant next steps.

The agent should act as an orchestration layer rather than simply being a text-generation component.

---

# 14. Example End-to-End Scenario

### User Prompt

> "Show me the top 10 regions by sales this year."

### Agent interpretation

```text
Intent:
Compare regions by sales.

Dimension:
Region

Measure:
Sales

Time filter:
Current year

Ranking:
Top 10

Visualization:
Horizontal bar chart
```

### Query generation

The agent creates the required analytical query against the available semantic model.

### Visualization

Power BI generates a bar chart showing:

```text
Region A  ███████████████
Region B  █████████████
Region C  ███████████
...
```

### Insight

The agent explains:

> "Region A generated the highest sales this year, followed by Region B and Region C."

### Potential next step

> "You can drill into the top regions by product category or month to identify the main drivers of performance."

---

# 15. Another Example

### User Prompt

> "How has our revenue changed month over month this year?"

### Agent interpretation

```text
Intent:
Analyze revenue trend.

Dimension:
Month

Measure:
Revenue

Filter:
Current year

Analysis:
Month-over-month trend

Visualization:
Line chart
```

### Expected output

The Power BI visual displays monthly revenue across the year.

The insight layer can identify:

- Overall upward/downward trend.
- Highest and lowest months.
- Significant changes.
- Potential periods requiring investigation.

---

# 16. Handling Ambiguous Prompts

Natural-language requests may be incomplete or ambiguous.

For example:

> "Show sales performance."

The agent may not know whether the user wants:

- Sales by month.
- Sales by region.
- Sales by product.
- Sales growth.
- Total sales.
- Sales versus target.

Instead of making an unreliable assumption, the agent should request clarification when the ambiguity materially affects the result.

Example:

> "Would you like to see sales performance by month, region, or product?"

This creates a conversational workflow rather than forcing the user to provide a technically precise request.

---

# 17. Error Handling and Validation

A production-oriented implementation should include validation at multiple points.

### Input validation

Check whether the request can be interpreted and whether required context is available.

### Semantic validation

Verify that requested business terms map to valid data fields or measures.

### Query validation

Validate generated queries before execution.

### Data validation

Check for:

- Missing data.
- Unexpected values.
- Empty results.
- Unsupported filters.
- Invalid date ranges.

### Visualization validation

Ensure the selected visual is compatible with the returned data.

### Insight validation

Ensure insights are supported by the retrieved data and avoid unsupported claims.

---

# 18. Security and Governance Considerations

Because the system works with business data, security should be considered from the beginning.

Potential considerations include:

- Authentication and authorization.
- Role-based access control.
- Power BI permissions.
- Row-level security.
- Data-source permissions.
- Secure API communication.
- Protection of sensitive business information.
- Logging and monitoring.
- Auditability of generated queries and outputs.

The agent should respect the permissions of the user requesting the analysis and should not expose data the user is not authorized to access.

---

# 19. Benefits of the Architecture

The proposed architecture provides several benefits.

### Natural-language accessibility

Users can interact with BI systems using familiar business language.

### Automation

Multiple manual BI tasks are combined into an automated workflow.

### Modularity

The architecture separates intent understanding, data access, visualization, and insight generation.

### Extensibility

Additional visualization types, data sources, analytical capabilities, and business rules can be incorporated later.

### Consistency

Visualization and metric-selection rules can be standardized across users.

### Scalability

The agent can potentially support multiple business questions and datasets without requiring a separate manually designed report for every question.

---

# 20. Potential Technology Components

The exact technology stack can be finalized based on project constraints, but the architecture may contain:

| Layer | Possible Technology |
|---|---|
| User Interface | Web application / Power BI interface |
| AI / Agent | LLM + agent orchestration framework |
| Semantic Understanding | Metadata / semantic model |
| Data Query | SQL / DAX / Power BI query mechanisms |
| BI Visualization | Microsoft Power BI |
| Data Source | SQL database / data warehouse / existing BI model |
| Integration | APIs / Power BI APIs |
| Authentication | Enterprise identity and access management |
| Monitoring | Application and agent logs |

These are architectural possibilities rather than mandatory technology choices.

---

# 21. Core Workflow Summary

The complete workflow can be summarized as:

```text
User asks a business question
            ↓
AI understands the intent
            ↓
Identify relevant data and metrics
            ↓
Map business terms to semantic model
            ↓
Generate and validate query
            ↓
Retrieve required data
            ↓
Select appropriate visualization
            ↓
Generate Power BI visual
            ↓
Analyze the result
            ↓
Generate insights
            ↓
Provide actionable recommendations
            ↓
Present result to user
```

---

# 22. Key Differentiator

The main differentiator of Prompt to Plot is that it does not stop at **natural-language-to-query** or **natural-language-to-chart**.

It aims to provide an end-to-end workflow:

> **Ask → Analyze → Visualize → Explain → Act**

This makes the solution focused on the complete business-analysis experience rather than only automating one technical step.

---

# 23. Project Scope

### In Scope

- Natural-language business questions.
- Intent detection.
- Metric and dimension identification.
- Semantic-model mapping.
- Query generation.
- Visualization recommendation.
- Power BI visual generation/integration.
- Insight generation.
- Actionable recommendations.
- Basic clarification and error handling.

### Potential Future Scope

- Multi-turn conversational analytics.
- Automated dashboard creation.
- Cross-report analysis.
- Advanced anomaly detection.
- Forecasting.
- Predictive analytics.
- Automated drill-down suggestions.
- Personalized recommendations.
- Voice-based BI interaction.
- Support for multiple BI platforms.
- Automated report narratives.

---

# 24. Success Criteria

The project can be evaluated using measurable outcomes such as:

### Efficiency

How much manual effort is reduced compared with creating the same visual manually.

### Accuracy

Whether the agent correctly identifies the intended metrics, dimensions, filters, and visualization.

### Relevance

Whether the generated visualization actually answers the user's business question.

### Insight Quality

Whether the generated insights accurately reflect the underlying data.

### Usability

Whether users can obtain useful results without requiring advanced Power BI knowledge.

### Reliability

Whether the system handles ambiguous, invalid, or unsupported requests appropriately.

---

# 25. Final Project Summary

Prompt to Plot is an AI-powered agent that bridges the gap between **business questions and business intelligence**.

Traditional BI workflows often require users to understand data structures, select metrics, write queries, configure visualizations, and interpret results manually. Prompt to Plot automates these steps through natural-language interaction.

The agent understands the user's intent, identifies the relevant data and metrics, generates the required analytical query, selects an appropriate Power BI visualization, and produces data-backed insights and potential actions.

The overall vision is to make BI more **accessible, automated, efficient, and decision-oriented**.

### One-line summary
 
> **Prompt to Plot turns a natural-language business question into a relevant visualization and actionable insight with minimal manual BI effort.**

---

# 26. Hackathon Submission Notes

Per the Hackathon 2026 requirements, we have explicitly documented the following architectural decisions and reusable components:

### Reusable Component: The Deterministic Security Hooks (`backend/security/hooks.py`)
To satisfy the *Best Harness* requirement of offering a component another team could lift into a different project, we present our **Deterministic Control Layer**. 
Most teams rely on system prompts for security (e.g., "Do not drop tables", "Do not hallucinate"). Our hook library strips validation away from the LLM. It intercepts inputs and outputs at lifecycle boundaries (before-model, before-tool, after-tool) and applies deterministic Python validation (Regex AST parsing for SQL drops, exact numeric matching for hallucination grounding). Any team building a LangGraph or agentic pipeline can drop this `hooks.py` file into their project to immediately secure their tool executions without changing their LLM.

### Architectural Pivot: Power BI vs. Plotly.js
Early drafts of this documentation aimed to integrate deeply with Microsoft Power BI. However, during the hackathon, we pivoted to an **Agent-Driven Plotly.js Architecture**. 
**Why?** Power BI requires heavy licensing, slow embedded iframe rendering, and complex semantic model setups that are rigid for an autonomous agent. By generating native `Plotly JSON` schemas directly from the agent and rendering them client-side in the browser, our system runs orders of magnitude faster, is completely open-source, and gives the LLM total control over styling, layout, and chart selection in real-time.
