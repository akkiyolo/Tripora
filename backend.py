import os
import certifi
from dotenv import load_dotenv
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres import PostgresSaver

load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from typing import TypedDict, Annotated
import operator
import uuid

import psycopg
from psycopg.rows import dict_row

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import interrupt, Command
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langchain_groq import ChatGroq
from tools.tavily_tool import tavily_search
from tools.flight_tool import search_flights
from tools.booking_tool import reserve_flight, reserve_hotel, charge_payment


def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Please add your Render PostgreSQL External Database URL to .env"
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing. Please add it to your .env file.")


# =========================
# LLM
# =========================

llm = ChatGroq(
    model="qwen/qwen3.6-27b",
    api_key=GROQ_API_KEY
)


# =========================
# State
# =========================

class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str
    flight_results: str
    hotel_results: str
    itinerary: str
    booking_status: str          # "" | "awaiting_payment" | "confirmed" | "cancelled" | "payment_failed"
    booking_summary: str
    llm_calls: int


# =========================
# Flight Agent
# =========================

def flight_agent(state: TravelState):
    query = state["user_query"]
    flight_data = search_flights(query)

    return {
        "flight_results": flight_data,
        "messages": [
            AIMessage(content="Flight results fetched.")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }



# =========================
# Hotel Agent
# =========================

def hotel_agent(state: TravelState):
    query = f"Best hotels for {state['user_query']}"
    hotel_results = tavily_search(query)

    return {
        "hotel_results": hotel_results,
        "messages": [
            AIMessage(content="Hotel information fetched.")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }




# =========================
# Itinerary Agent
# =========================

def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query:
{state['user_query']}

Flight Results:
{state['flight_results']}

Hotel Results:
{state['hotel_results']}

Make the itinerary practical, budget-aware, and easy to follow.
"""

    response = llm.invoke([
        SystemMessage(content="You are an expert travel planner."),
        HumanMessage(content=prompt)
    ])

    return {
        "itinerary": response.content,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1
    }



# =========================
# Final Response Agent
# =========================

def final_agent(state: TravelState):
    final_prompt = f"""
Generate the final travel response for the user.

User Request:
{state['user_query']}

Flights:
{state['flight_results']}

Hotels:
{state['hotel_results']}

Itinerary:
{state['itinerary']}

Format the final answer beautifully using these sections:

1. Trip Summary
2. Flight Information
3. Hotel Suggestions
4. Day-by-Day Itinerary
5. Estimated Budget
6. Final Recommendations

Important:
- Be clear and practical.
- Mention that live flight API may not provide ticket prices if pricing is unavailable.
- Keep the response useful for real travel planning.
- Mention that the user can approve this plan to move to booking.
"""

    response = llm.invoke([
        SystemMessage(content="You are a professional AI travel booking assistant."),
        HumanMessage(content=final_prompt)
    ])

    return {
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


# =========================
# Booking Agent (reservation phase)
# =========================

def booking_agent(state: TravelState):
    """
    Only entered via booking_graph, which is only triggered by an explicit
    user approval call. Reserves the flight + hotel, then hard-stops
    before payment via interrupt(). The graph will not proceed past this
    point until the user explicitly confirms payment through a separate
    API call that resumes this exact node with Command(resume=...).
    """
    flight_reservation = reserve_flight(state["flight_results"])
    hotel_reservation = reserve_hotel(state["hotel_results"])

    summary = (
        f"Flight: {flight_reservation['summary']}\n"
        f"Hotel: {hotel_reservation['summary']}\n"
        f"Total estimated cost: {flight_reservation['price'] + hotel_reservation['price']}"
    )

    user_decision = interrupt({
        "type": "payment_confirmation_required",
        "booking_summary": summary,
    })

    if user_decision != "confirm":
        return {
            "booking_status": "cancelled",
            "booking_summary": summary,
            "messages": [AIMessage(content="Booking cancelled before payment.")],
        }

    return {
        "booking_status": "awaiting_payment",
        "booking_summary": summary,
        "messages": [AIMessage(content="Reservation held. Proceeding to payment.")],
    }


# =========================
# Payment Agent (only reachable after interrupt is resumed with "confirm")
# =========================

def payment_agent(state: TravelState):
    if state.get("booking_status") != "awaiting_payment":
        return {
            "messages": [AIMessage(content="Payment skipped — booking was not confirmed.")]
        }

    result = charge_payment(state["booking_summary"])

    return {
        "booking_status": "confirmed" if result["success"] else "payment_failed",
        "messages": [AIMessage(content=result["message"])],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# =========================
# Build Planning Graph (unchanged flow: plan only, no booking)
# =========================

graph = StateGraph(TravelState)

graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("final_agent", final_agent)

graph.add_edge(START, "flight_agent")
graph.add_edge("flight_agent", "hotel_agent")
graph.add_edge("hotel_agent", "itinerary_agent")
graph.add_edge("itinerary_agent", "final_agent")
graph.add_edge("final_agent", END)


# =========================
# Build Booking Graph (separate graph, same checkpointer + thread_id)
# =========================
# Kept separate from the planning graph on purpose: travel_graph already
# reaches END once the itinerary is produced. Re-entering a finished run
# mid-graph isn't something LangGraph supports cleanly, so booking is its
# own small graph that shares the thread's checkpointed state instead.

booking_subgraph = StateGraph(TravelState)
booking_subgraph.add_node("booking_agent", booking_agent)
booking_subgraph.add_node("payment_agent", payment_agent)

booking_subgraph.add_edge(START, "booking_agent")
booking_subgraph.add_edge("booking_agent", "payment_agent")
booking_subgraph.add_edge("payment_agent", END)


# =========================
# PostgreSQL Checkpointer (shared across both graphs)
# =========================
DATABASE_URL = get_database_url()

pool = ConnectionPool(
    DATABASE_URL,
    max_size=10,
    kwargs={
        "autocommit": True,
        "row_factory": dict_row
    }
)

checkpointer = PostgresSaver(pool)
checkpointer.setup()

travel_graph = graph.compile(checkpointer=checkpointer)
booking_graph = booking_subgraph.compile(checkpointer=checkpointer)


# =========================
# Function for FastAPI - plan a trip
# =========================

def run_travel_agent(user_input: str, thread_id: str | None = None):
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    result = travel_graph.invoke(
        {
            "messages": [
                HumanMessage(content=user_input)
            ],
            "user_query": user_input,
            "flight_results": "",
            "hotel_results": "",
            "itinerary": "",
            "booking_status": "",
            "booking_summary": "",
            "llm_calls": 0
        },
        config=config
    )

    final_answer = result["messages"][-1].content

    return {
        "thread_id": thread_id,
        "answer": final_answer,
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "itinerary": result.get("itinerary", ""),
        "llm_calls": result.get("llm_calls", 0),
    }


# =========================
# Function for FastAPI - approve the plan, start reservation
# =========================

def approve_travel_plan(thread_id: str):
    """
    Pulls the already-planned itinerary/flight/hotel results from the
    planning thread's checkpoint, then kicks off the booking graph on
    the same thread_id. This will run booking_agent and pause at the
    interrupt() call, waiting for payment confirmation.
    """
    config = {"configurable": {"thread_id": thread_id}}

    planning_state = travel_graph.get_state(config)
    if not planning_state or not planning_state.values.get("itinerary"):
        raise ValueError("No completed itinerary found for this thread_id.")

    result = booking_graph.invoke(
        {
            "messages": [],
            "user_query": planning_state.values["user_query"],
            "flight_results": planning_state.values["flight_results"],
            "hotel_results": planning_state.values["hotel_results"],
            "itinerary": planning_state.values["itinerary"],
            "booking_status": "",
            "booking_summary": "",
            "llm_calls": planning_state.values.get("llm_calls", 0),
        },
        config=config
    )

    # Graph paused at interrupt() — surface the booking summary so the
    # frontend can show the user exactly what they're about to pay for.
    interrupts = result.get("__interrupt__", [])
    booking_summary = interrupts[0].value.get("booking_summary") if interrupts else None

    return {
        "thread_id": thread_id,
        "status": "awaiting_payment_confirmation",
        "booking_summary": booking_summary,
    }


# =========================
# Function for FastAPI - explicit payment confirmation, resumes graph
# =========================

def confirm_payment(thread_id: str, confirm: bool):
    """
    The ONLY function in this file that can move a booking past payment.
    Resumes the interrupted booking_graph with the user's explicit
    decision. If confirm=False, the graph cancels the booking instead
    of charging anything.
    """
    config = {"configurable": {"thread_id": thread_id}}

    result = booking_graph.invoke(
        Command(resume="confirm" if confirm else "cancel"),
        config=config
    )

    return {
        "thread_id": thread_id,
        "booking_status": result.get("booking_status", "unknown"),
        "message": result["messages"][-1].content if result.get("messages") else "",
    }