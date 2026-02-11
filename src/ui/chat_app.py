"""
GroundwaterGPT Chat Interface

Streamlit-based chat UI for the Groundwater Research Agent.
"""

import sys
from pathlib import Path

import streamlit as st

# Add project root and src to path for imports
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "src"))

from agent import GroundwaterAgent, LLMProvider

# Page configuration
st.set_page_config(
    page_title="GroundwaterGPT",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown(
    """
<style>
    .stApp {
        max-width: 1200px;
        margin: 0 auto;
    }
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
    .user-message {
        background-color: #e3f2fd;
    }
    .assistant-message {
        background-color: #f5f5f5;
    }
</style>
""",
    unsafe_allow_html=True,
)

# Title
st.title("💧 GroundwaterGPT")
st.markdown("*AI-powered groundwater research assistant for Fort Myers, FL*")

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")

    # Provider selection
    provider_options = {
        "Google Gemini": LLMProvider.GEMINI,
        "Ollama (Local)": LLMProvider.OLLAMA,
        "OpenAI": LLMProvider.OPENAI,
        "Anthropic": LLMProvider.ANTHROPIC,
    }

    selected_provider = st.selectbox(
        "LLM Provider",
        options=list(provider_options.keys()),
        index=0,
        help="Select the LLM provider. Gemini has a free tier.",
    )

    provider = provider_options[selected_provider]

    # Model selection based on provider
    model_options = {
        LLMProvider.OLLAMA: ["llama3.2", "qwen2.5:7b", "mistral", "deepseek-r1:7b"],
        LLMProvider.OPENAI: ["gpt-4o", "gpt-4o-mini", "gpt-4.1"],
        LLMProvider.ANTHROPIC: ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229"],
        LLMProvider.GEMINI: ["gemini-2.0-flash", "gemini-1.5-pro"],
    }

    model = st.selectbox(
        "Model",
        options=model_options[provider],
        index=0,
    )

    # API key input for non-local providers
    if provider != LLMProvider.OLLAMA:
        api_key_names = {
            LLMProvider.OPENAI: "OPENAI_API_KEY",
            LLMProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
            LLMProvider.GEMINI: "GOOGLE_API_KEY",
        }
        env_var = api_key_names[provider]
        api_key = st.text_input(
            f"{env_var}", type="password", help=f"Enter your API key for {selected_provider}"
        )
        if api_key:
            import os

            os.environ[env_var] = api_key

    st.divider()

    # Knowledge base info
    st.header("📚 Knowledge Base")

    if "agent" in st.session_state:
        kb_info = st.session_state.agent.get_knowledge_info()
        st.metric("Document Chunks", kb_info.get("total_chunks", 0))
        st.caption("Reference Documents:")
        for pdf in kb_info.get("pdf_names", []):
            st.caption(f"  • {pdf}")
    else:
        st.caption("Loading...")

    st.divider()

    # Tools info
    st.header("🛠️ Available Tools")
    tools_list = [
        "📊 Query groundwater data",
        "🔮 Water level predictions",
        "🌊 Seasonal analysis",
        "⚠️ Anomaly detection",
        "📋 Data quality report",
        "📚 Document search",
    ]
    for tool in tools_list:
        st.caption(tool)

    st.divider()

    # Clear chat button
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        if "agent" in st.session_state:
            st.session_state.agent.clear_history()
        st.rerun()

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

if "agent" not in st.session_state:
    with st.spinner("🔄 Initializing GroundwaterGPT..."):
        try:
            st.session_state.agent = GroundwaterAgent(
                provider=provider,
                model=model,
                verbose=False,
            )
        except Exception as e:
            st.error(f"Failed to initialize agent: {str(e)}")
            st.stop()

# Check if provider/model changed
if (
    st.session_state.get("current_provider") != provider
    or st.session_state.get("current_model") != model
):
    with st.spinner("🔄 Switching model..."):
        try:
            st.session_state.agent = GroundwaterAgent(
                provider=provider,
                model=model,
                verbose=False,
            )
            st.session_state.current_provider = provider
            st.session_state.current_model = model
        except Exception as e:
            st.error(f"Failed to switch model: {str(e)}")

# Suggested prompts
if not st.session_state.messages:
    st.markdown("### 👋 Welcome! Try asking:")

    col1, col2, col3 = st.columns(3)

    suggested_prompts = [
        "What's the current groundwater level?",
        "Show me seasonal patterns",
        "Predict water levels for next week",
        "Are there any anomalies in the data?",
        "What is an aquifer?",
        "Explain the data quality",
    ]

    for i, prompt in enumerate(suggested_prompts):
        col = [col1, col2, col3][i % 3]
        with col:
            if st.button(prompt, key=f"suggest_{i}", use_container_width=True):
                st.session_state.messages.append({"role": "user", "content": prompt})
                st.rerun()

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Ask about groundwater data, predictions, or hydrogeology..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get agent response
    with st.chat_message("assistant"):
        with st.spinner("🤔 Thinking..."):
            try:
                response = st.session_state.agent.chat(prompt)
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
            except Exception as e:
                error_msg = f"❌ Error: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})

# Footer
st.divider()
st.caption(
    """
💧 **GroundwaterGPT** | USGS Site 262724081260701 (Lee County, FL)
📊 Data: 2014-2023 | 🤖 Model: Ridge Regression (R² ≈ 0.86)
📚 Knowledge: Hydrogeology reference documents
"""
)
