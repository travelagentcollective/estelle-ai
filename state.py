from typing import Annotated, TypedDict, Sequence
from langgraph.graph.message import BaseMessage, add_messages

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]