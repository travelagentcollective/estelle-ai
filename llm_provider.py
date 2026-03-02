import os
from dotenv import load_dotenv


from langchain_openai import ChatOpenAI

# LLM
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL="gpt-4o-mini"

def call_llm() -> ChatOpenAI:
    from nodes import TOOLS
    
    llm = ChatOpenAI(model=MODEL, api_key=OPENAI_API_KEY, temperature=0.5)
    llm_with_tools = llm.bind_tools(TOOLS)
    return llm_with_tools
