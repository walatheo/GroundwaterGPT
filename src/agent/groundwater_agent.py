"""GroundwaterGPT Agent - Main Agent Implementation.

Agentic RAG system combining:
- Hydrogeology document knowledge base (ChromaDB)
- Groundwater data analysis tools
- ML-based predictions

Uses LangGraph for modern, reliable agent architecture.
"""

import os
from typing import Generator, List, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from .knowledge import get_knowledge_stats, search_knowledge
from .llm_factory import LLMProvider, get_llm
from .tools import GROUNDWATER_TOOLS

# System prompt for the agent
SYSTEM_PROMPT = """You are GroundwaterGPT, an expert AI assistant specializing in \
groundwater hydrology and water resources.

**Your Expertise:**
- Groundwater monitoring and analysis across 36 USGS sites in 5 Florida counties
- Interpretation of USGS water level data for Biscayne, Floridan, and Surficial aquifers
- Hydrogeology concepts and terminology
- Water table dynamics, aquifer behavior, and seasonal patterns
- Machine learning predictions for water levels

**Your Tools:**
1. `list_available_sites` - Discover which monitoring sites exist (filter by county/aquifer)
2. `query_site_data` - Get data and statistics for a specific USGS site
3. `query_groundwater_data` - Query the consolidated groundwater dataset
4. `get_water_level_prediction` - Get ML-based water level forecasts
5. `analyze_seasonal_patterns` - Analyze wet/dry season patterns
6. `detect_anomalies` - Find unusual water level events
7. `get_data_quality_report` - Check data quality and coverage
8. `generate_time_series_plot` - Generate chart data for a single site
9. `generate_comparison_chart` - Generate multi-site comparison chart
10. `create_research_experiment_plan` - Create a structured experiment protocol
11. `list_research_experiment_plans` - List saved experiment plans
12. `log_experiment_run` - Log run configs, metrics, and findings
13. `draft_research_paper` - Generate a manuscript draft from logged experiments
14. `search_hydrogeology_docs` - Search reference documents for concepts

**Workflow — ALWAYS follow this pattern:**
1. Use `list_available_sites` to find relevant sites when the user mentions \
a county, aquifer, or site name.
2. Use `query_site_data` to get specific data for those sites.
3. Use analysis tools (seasonal, anomaly, prediction) when the question \
requires deeper investigation.
4. For researcher workflows, create a plan, log runs, then draft a paper.
5. Search docs for hydrogeology concepts you need to explain.

**Guidelines:**
- Always search relevant knowledge before answering hydrogeology questions
- Use tools to provide data-driven insights — never guess at numbers
- Cite sources when referencing documents
- Explain technical concepts in accessible terms
- Be precise with units (feet below land surface)
- Acknowledge uncertainty when appropriate

**Response Style:**
- Use clear headings and bullet points
- Include relevant data and statistics from your tool calls
- Provide actionable insights
"""

DOC_RETRIEVAL_K = int(os.getenv("GROUNDWATERGPT_DOC_RETRIEVAL_K", "4"))
DOC_RETRIEVAL_SCORE_THRESHOLD = float(
    os.getenv("GROUNDWATERGPT_DOC_RETRIEVAL_SCORE_THRESHOLD", "0.45")
)


@tool
def search_hydrogeology_docs(query: str) -> str:
    """Search the hydrogeology knowledge base for relevant information.

    Args:
        query: The search query about hydrogeology concepts, terminology, or methods

    Returns:
        Relevant excerpts from hydrogeology reference documents
    """
    docs = search_knowledge(
        query,
        k=DOC_RETRIEVAL_K,
        score_threshold=DOC_RETRIEVAL_SCORE_THRESHOLD,
    )

    if not docs:
        return "No relevant documents found in the knowledge base."

    result = "📚 **Relevant Knowledge Base Results:**\n\n"
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source_file", "Unknown")
        page = doc.metadata.get("page", "?")

        # Truncate content if too long
        content = (
            doc.page_content[:500] + "..." if len(doc.page_content) > 500 else doc.page_content
        )

        result += f"**Source {i}:** {source} (page {page})\n"
        result += f"{content}\n\n"

    return result


class GroundwaterAgent:
    """GroundwaterGPT Research Agent.

    Combines RAG with custom tools for comprehensive groundwater analysis.
    Uses a simple retrieval-augmented approach for local models,
    or LangGraph ReAct for larger models (GPT-4, Claude, Gemini).
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        verbose: bool = False,
        use_react: bool = True,  # ReAct enabled by default (Ollama supports it)
    ):
        """Initialize the Groundwater Agent.

        Args:
            provider: LLM provider (default: from config)
            model: Model name (default: from config)
            temperature: Response temperature
            verbose: Enable verbose output
            use_react: Use ReAct agent (recommended for all models)
        """
        self.llm = get_llm(provider=provider, model=model, temperature=temperature)
        self.verbose = verbose
        self.use_react = use_react

        # Combine all tools
        self.tools = GROUNDWATER_TOOLS + [search_hydrogeology_docs]
        self.tools_dict = {tool.name: tool for tool in self.tools}

        if use_react:
            # Create the LangGraph ReAct agent for larger models
            self.agent = create_react_agent(
                model=self.llm,
                tools=self.tools,
                prompt=SYSTEM_PROMPT,
            )
        else:
            self.agent = None

        # Chat history
        self.chat_history: List = []

    def _detect_intent(self, message: str) -> str:
        """Detect user intent to select appropriate tool."""
        message_lower = message.lower()

        if any(word in message_lower for word in ["predict", "forecast", "future", "next"]):
            return "prediction"
        elif any(word in message_lower for word in ["season", "wet", "dry", "pattern"]):
            return "seasonal"
        elif any(word in message_lower for word in ["anomal", "unusual", "outlier", "extreme"]):
            return "anomaly"
        elif any(word in message_lower for word in ["quality", "coverage", "missing", "gap"]):
            return "quality"
        elif any(
            word in message_lower
            for word in ["what is", "define", "explain", "term", "meaning", "glossary"]
        ):
            return "knowledge"
        else:
            return "data"

    def _get_context(self, message: str, intent: str) -> str:
        """Get relevant context based on intent."""
        context_parts = []

        # Always add data summary for grounding
        try:
            from .tools import query_groundwater_data

            data_summary = query_groundwater_data.invoke({"stat_type": "summary"})
            context_parts.append(f"## Current Data:\n{data_summary}")
        except Exception as e:
            if self.verbose:
                print(f"Error getting data: {e}")

        # Add specific context based on intent
        if intent == "prediction":
            try:
                from .tools import get_water_level_prediction

                prediction = get_water_level_prediction.invoke({})
                context_parts.append(f"## Prediction:\n{prediction}")
            except Exception as e:
                if self.verbose:
                    print(f"Error getting prediction: {e}")

        elif intent == "seasonal":
            try:
                from .tools import analyze_seasonal_patterns

                seasonal = analyze_seasonal_patterns.invoke({})
                context_parts.append(f"## Seasonal Analysis:\n{seasonal}")
            except Exception as e:
                if self.verbose:
                    print(f"Error getting seasonal: {e}")

        elif intent == "anomaly":
            try:
                from .tools import detect_anomalies

                anomalies = detect_anomalies.invoke({})
                context_parts.append(f"## Anomaly Detection:\n{anomalies}")
            except Exception as e:
                if self.verbose:
                    print(f"Error getting anomalies: {e}")

        elif intent == "quality":
            try:
                from .tools import get_data_quality_report

                quality = get_data_quality_report.invoke({})
                context_parts.append(f"## Data Quality:\n{quality}")
            except Exception as e:
                if self.verbose:
                    print(f"Error getting quality: {e}")

        elif intent == "knowledge":
            try:
                docs = search_knowledge(message, k=3)
                if docs:
                    context_parts.append("## Knowledge Base:\n")
                    for i, doc in enumerate(docs, 1):
                        source = doc.metadata.get("source_file", "Unknown")
                        context_parts.append(
                            f"**Source {i}** ({source}):\n{doc.page_content[:400]}...\n"
                        )
            except Exception as e:
                if self.verbose:
                    print(f"Error searching knowledge: {e}")

        return "\n\n".join(context_parts)

    def chat(self, message: str) -> str:
        """Send a message and get a response.

        Args:
            message: User message

        Returns:
            Agent response
        """
        if self.use_react and self.agent:
            return self._chat_react(message)
        else:
            return self._chat_simple(message)

    def _chat_react(self, message: str) -> str:
        """Use ReAct agent for tool calling (larger models)."""
        messages = self.chat_history + [HumanMessage(content=message)]
        result = self.agent.invoke({"messages": messages})

        response_messages = result.get("messages", [])
        if response_messages:
            for msg in reversed(response_messages):
                if isinstance(msg, AIMessage) and msg.content:
                    response = msg.content
                    break
            else:
                response = "I couldn't generate a response. Please try again."
        else:
            response = "No response generated."

        self.chat_history.append(HumanMessage(content=message))
        self.chat_history.append(AIMessage(content=response))

        return response

    def _chat_simple(self, message: str) -> str:
        """Simple retrieval-augmented chat (works with smaller models)."""
        # Detect intent and get context
        intent = self._detect_intent(message)
        context = self._get_context(message, intent)

        # Build the prompt with context
        prompt = f"""{SYSTEM_PROMPT}

{context}

---

User Question: {message}

Please provide a helpful, accurate response based on the data and context above.
Use the specific numbers and statistics from the context.
Be concise but thorough."""

        # Generate response
        response = self.llm.invoke(prompt)

        # Update history
        self.chat_history.append(HumanMessage(content=message))
        self.chat_history.append(AIMessage(content=response.content))

        return response.content

    def stream(self, message: str) -> Generator[str, None, None]:
        """Stream a response (for real-time display).

        Args:
            message: User message

        Yields:
            Response chunks
        """
        if self.use_react and self.agent:
            # Use ReAct streaming
            messages = self.chat_history + [HumanMessage(content=message)]

            full_response = ""
            for chunk in self.agent.stream({"messages": messages}):
                if "messages" in chunk:
                    for msg in chunk["messages"]:
                        if isinstance(msg, AIMessage) and msg.content:
                            full_response = msg.content
                            yield msg.content

            self.chat_history.append(HumanMessage(content=message))
            if full_response:
                self.chat_history.append(AIMessage(content=full_response))
        else:
            # Simple streaming for local models
            intent = self._detect_intent(message)
            context = self._get_context(message, intent)

            prompt = f"""{SYSTEM_PROMPT}

{context}

---

User Question: {message}

Please provide a helpful, accurate response based on the data and context above."""

            full_response = ""
            for chunk in self.llm.stream(prompt):
                if chunk.content:
                    full_response += chunk.content
                    yield chunk.content

            self.chat_history.append(HumanMessage(content=message))
            self.chat_history.append(AIMessage(content=full_response))

    def clear_history(self):
        """Clear the chat history."""
        self.chat_history = []

    def get_knowledge_info(self) -> dict:
        """Get information about the knowledge base."""
        return get_knowledge_stats()

    def get_tools_info(self) -> List[str]:
        """Get list of available tools."""
        return [f"{t.name}: {t.description}" for t in self.tools]


def create_agent(
    provider: Optional[LLMProvider] = None,
    model: Optional[str] = None,
    verbose: bool = False,
    use_react: bool = True,
) -> GroundwaterAgent:
    """Factory function to create a GroundwaterGPT agent.

    Args:
        provider: LLM provider (default: from config)
        model: Model name (default: from config)
        verbose: Enable verbose output
        use_react: Use ReAct agent (default True)

    Returns:
        Configured GroundwaterAgent instance
    """
    return GroundwaterAgent(
        provider=provider,
        model=model,
        verbose=verbose,
        use_react=use_react,
    )


# Quick test
if __name__ == "__main__":
    print("🌊 Testing GroundwaterGPT Agent...")

    agent = create_agent(verbose=True)

    # Test knowledge base
    print("\n📚 Knowledge Base Info:")
    print(agent.get_knowledge_info())

    # Test a query
    print("\n💬 Test Query:")
    response = agent.chat("What is the current groundwater level and recent trend?")
    print(response)
