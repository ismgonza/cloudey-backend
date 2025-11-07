import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

load_dotenv()


def get_anthropic_client() -> ChatAnthropic:
    """Initialize and return Anthropic client."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not found in environment variables")
    
    return ChatAnthropic(
        model="claude-3-5-sonnet-20241022",
        api_key=api_key,
        temperature=0,
    )


def get_openai_client() -> ChatOpenAI:
    """Initialize and return OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables")
    
    return ChatOpenAI(
        model="gpt-4.1-mini",
        api_key=api_key,
        temperature=0,
    )

