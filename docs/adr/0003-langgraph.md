# 0003: LangGraph for the agent workflow

## Decision
The workflow is a LangGraph `StateGraph` with one node per agent, a conditional edge from the coverage check back to the planner, and list reducers for the trace and results.

## Options considered
- **A hand-written loop** (as in my earlier project TriMatch). Fine for one agent with tools; with five roles and a loop back, the control flow becomes harder to read.
- **LangChain agents with tool calling.** The model would choose which tool to call next. Here the order is fixed and known, so letting a model choose it adds risk without benefit.
- **LangGraph (chosen).** The graph is the documentation: nodes and edges are declared in one place, and the state passed between agents is a typed dict.

## Trade-off
One more dependency, and LangGraph's typing is loose (one `type: ignore` on the compiled graph's type). Only `langgraph` is used, not LangChain's model wrappers: providers are plain HTTP (ADR 0007).
