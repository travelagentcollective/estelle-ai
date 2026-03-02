from langgraph.graph import StateGraph, START, END
from state import AgentState
from nodes import chatbot, should_continue, TOOL_NODE

builder = StateGraph(AgentState)

builder.add_node("chatbot", chatbot)

builder.add_node("tools", TOOL_NODE)


builder.add_edge(START, "chatbot")
builder.add_conditional_edges("chatbot", should_continue)
builder.add_edge("tools", END)
builder.add_edge("chatbot", END)


