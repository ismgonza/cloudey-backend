"""LangGraph agent logic and workflow orchestration."""

from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from app.cloud.oci.tools import create_oci_tools
from app.models import get_openai_client
from app.prompts import get_system_prompt
from app.sysconfig import DatabaseConfig

# Global connection pool and checkpointer
_connection_pool = None
_checkpointer = None

async def get_checkpointer():
    """Get or create the async PostgreSQL checkpointer instance."""
    global _connection_pool, _checkpointer
    if _checkpointer is None:
        # Create async connection pool for PostgreSQL
        _connection_pool = AsyncConnectionPool(
            conninfo=DatabaseConfig.DATABASE_URL,
            min_size=2,
            max_size=10,
            open=False  # Don't open automatically to avoid deprecation warning
        )
        # Open the pool
        await _connection_pool.open()
        
        # Create PostgreSQL checkpointer
        # Note: We skip setup() because tables are already created via init_schema.sql
        # and setup() uses CREATE INDEX CONCURRENTLY which can't run in a transaction
        _checkpointer = AsyncPostgresSaver(_connection_pool)
    return _checkpointer


def reducer(x: Sequence[BaseMessage], y: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Reducer function for messages state."""
    return list(x) + list(y)


class AgentState(TypedDict):
    """State for the agent graph."""
    messages: Annotated[Sequence[BaseMessage], reducer]


async def create_agent(model_provider: str = "openai", user_id: int = 1):
    """Create a LangGraph agent with tools.
    
    Args:
        model_provider: "openai" or "anthropic"
        user_id: User ID for accessing user-specific cloud configs
    """
    # Get the LLM client
    if model_provider == "openai":
        llm = get_openai_client()
    elif model_provider == "anthropic":
        from app.models import get_anthropic_client
        llm = get_anthropic_client()
    else:
        raise ValueError(f"Unknown model provider: {model_provider}")
    
    # Create user-specific tools
    oci_tools = create_oci_tools(user_id)
    all_tools = oci_tools  # Add more providers here: oci_tools + aws_tools + ...
    
    # Bind tools to LLM
    llm_with_tools = llm.bind_tools(all_tools)
    
    def agent_node(state: AgentState):
        """Agent node that processes messages."""
        # Add system message if not already present
        messages = list(state["messages"])
        if not any(isinstance(msg, SystemMessage) for msg in messages):
            system_prompt = get_system_prompt()
            messages = [SystemMessage(content=system_prompt)] + messages
        
        # Clean up any incomplete tool calls (messages with tool_calls but no following tool responses)
        cleaned_messages = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            
            # If this is an AIMessage with tool_calls
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                # Check if there are corresponding tool responses after this message
                has_responses = False
                if i + 1 < len(messages):
                    # Look for ToolMessage responses
                    j = i + 1
                    tool_call_ids = {tc.get("id") for tc in msg.tool_calls if isinstance(tc, dict) and "id" in tc}
                    if not tool_call_ids:
                        # Try alternate structure
                        tool_call_ids = {tc.id for tc in msg.tool_calls if hasattr(tc, "id")}
                    
                    while j < len(messages):
                        next_msg = messages[j]
                        # Check if it's a tool response
                        if hasattr(next_msg, "tool_call_id"):
                            if next_msg.tool_call_id in tool_call_ids:
                                tool_call_ids.discard(next_msg.tool_call_id)
                            j += 1
                        elif isinstance(next_msg, AIMessage):
                            # Hit another AI message, stop looking
                            break
                        else:
                            j += 1
                    
                    has_responses = len(tool_call_ids) == 0
                
                # Only include this message if it has all responses, or convert to text-only
                if has_responses:
                    cleaned_messages.append(msg)
                else:
                    # Remove tool_calls to prevent OpenAI API error
                    cleaned_msg = AIMessage(content=msg.content if msg.content else "Thinking...")
                    cleaned_messages.append(cleaned_msg)
            else:
                cleaned_messages.append(msg)
            
            i += 1
        
        response = llm_with_tools.invoke(cleaned_messages)
        return {"messages": [response]}
    
    def should_continue(state: AgentState):
        """Check if we should continue to tools or end."""
        messages = state["messages"]
        if not messages:
            return END
        
        last_message = messages[-1]
        # Check if the last message has tool calls
        if isinstance(last_message, AIMessage):
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tools"
        return END
    
    # Create the graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(all_tools))
    
    # Add edges
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END,
        }
    )
    workflow.add_edge("tools", "agent")
    
    # Compile with async SQLite checkpointer (persistent storage)
    checkpointer = await get_checkpointer()
    app = workflow.compile(checkpointer=checkpointer)
    
    return app


async def get_conversation_history(thread_id: str):
    """Get conversation history for a thread from the checkpoint database.
    
    Args:
        thread_id: Thread ID (session_id) to fetch history for
    
    Returns:
        List of messages in the conversation
    """
    try:
        checkpointer = await get_checkpointer()
        config = {"configurable": {"thread_id": thread_id}}
        
        # Get the checkpoint state
        checkpoint = await checkpointer.aget(config)
        
        if not checkpoint or not checkpoint.get("channel_values"):
            return []
        
        # Extract messages from the state
        messages_data = checkpoint["channel_values"].get("messages", [])
        
        # Convert to simple dict format for API response
        result = []
        for msg in messages_data:
            # Skip system messages
            if isinstance(msg, SystemMessage):
                continue
            
            if isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                # Only include messages without tool calls (final responses)
                if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                    result.append({"role": "assistant", "content": msg.content})
        
        return result
    except Exception as e:
        print(f"Error fetching conversation history: {str(e)}")
        return []


async def delete_conversation_history(thread_id: str):
    """Delete conversation history for a thread from the checkpoint database.
    
    Args:
        thread_id: Thread ID (session_id) to delete
    """
    try:
        checkpointer = await get_checkpointer()
        
        # Access the underlying aiosqlite connection
        conn = checkpointer.conn
        
        # Delete all checkpoints for this thread
        await conn.execute(
            "DELETE FROM checkpoints WHERE thread_id = ?",
            (thread_id,)
        )
        await conn.commit()
    except Exception as e:
        print(f"Error deleting conversation history: {str(e)}")
        raise


async def query_agent(question: str, model_provider: str = "openai", user_id: int = 1, thread_id: str = "default"):
    """Query the agent with a question and return the response.
    
    Args:
        question: The user's question
        model_provider: "openai" or "anthropic"
        user_id: User ID for accessing user-specific cloud configs
        thread_id: Thread ID for conversation memory (session_id from frontend)
    
    Note:
        - thread_id is used by LangGraph to track conversation history
        - Each unique thread_id maintains separate conversation context
        - Conversations are persisted in PostgreSQL (checkpoints table)
    """
    try:
        agent = await create_agent(model_provider, user_id)
        
        # Prepare messages
        messages = [HumanMessage(content=question)]
        
        # Invoke the agent with thread_id for conversation persistence
        # LangGraph uses thread_id to:
        # 1. Load previous messages for this conversation
        # 2. Save new messages to SQLite after this query
        config = {"configurable": {"thread_id": thread_id}}
        result = await agent.ainvoke({"messages": messages}, config)
        
        # Extract the final response
        if result.get("messages"):
            # Find the last AI message that doesn't have tool calls
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage):
                    # Check if it has tool_calls attribute and if it's empty/None
                    if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                        return msg.content
                    # If it has tool calls, continue to find the response after tool execution
        
        return "I couldn't generate a response. Please try again."
    except Exception as e:
        return f"Error: {str(e)}"

