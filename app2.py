import os
import re
from typing import List, Tuple, Dict

import gradio as gr
from openai import OpenAI
import os
# set OPENAI_API_KEY in os environment
os.environ["OPENAI_API_KEY"] = "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"

# ---- 1) OpenAI client ----
client = OpenAI()  # uses OPENAI_API_KEY env var

# ---- 2) Simulated stock data (prototype / fake) ----
FAKE_STOCK_DB: Dict[str, Dict[str, str]] = {
    "AAPL": {"price": "182.40", "change": "+1.2%", "trend": "mild uptrend", "volatility": "low"},
    "TSLA": {"price": "214.10", "change": "-2.3%", "trend": "sideways", "volatility": "high"},
    "NVDA": {"price": "121.80", "change": "+0.8%", "trend": "uptrend", "volatility": "medium"},
}

DISCLAIMER = (
    "⚠ Educational prototype only. I’m not a financial advisor and I don’t provide investment advice."
)

# ---- 3) Very small intent/ticker detection (kept simple on purpose) ----
TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")

def extract_ticker(user_text: str) -> str:
    m = TICKER_RE.search(user_text.upper())
    return m.group(1) if m else ""

def classify_intent(user_text: str) -> str:
    t = user_text.lower()
    if any(k in t for k in ["should i buy", "buy", "sell", "hold", "invest"]):
        return "advice"
    if any(k in t for k in ["price", "how is", "doing", "performance", "trend"]):
        return "summary"
    if any(k in t for k in ["risk", "volatile", "volatility", "downside"]):
        return "risk"
    return "general"

# ---- 4) Core chatbot function (Gradio ChatInterface) ----
def chat_fn(message: str, history: List[Tuple[str, str]]) -> str:
    ticker = extract_ticker(message)
    intent = classify_intent(message)

    # A) Responsible refusal for "advice"
    if intent == "advice":
        return (
            f"{DISCLAIMER}\n\n"
            "I can help you *understand* recent trend/risk and what to look at (e.g., volatility, news catalysts, time horizon).\n"
            "If you tell me your goal (short-term vs long-term) and risk tolerance (low/medium/high), I’ll explain what factors matter."
        )

    # B) If ticker not recognized, ask clarification (err
       # B) If ticker not recognized, ask clarification (error recovery)
    if not ticker:
        return (
            f"{DISCLAIMER}\n\n"
            "Which stock ticker are you asking about? (e.g., AAPL, TSLA, NVDA)\n"
            "You can also ask: “Summarize TSLA” or “What are the risks of NVDA?”"
        )

    # C) If ticker not in fake DB, keep it prototype-simple
    if ticker not in FAKE_STOCK_DB:
        return (
            f"{DISCLAIMER}\n\n"
            f"I’m a prototype with simulated data and currently support: {', '.join(FAKE_STOCK_DB.keys())}.\n"
            "Try one of those tickers."
        )

    # D) Compose a structured context for the model (keeps answers consistent)
    data = FAKE_STOCK_DB[ticker]
    system_instructions = (
        "You are a helpful stock-explainer chatbot for beginners. "
        "You MUST follow these rules:\n"
        "1) Educational only; never give buy/sell/hold advice.\n"
        "2) Be transparent that the data is simulated for a prototype.\n"
        "3) Use short answers (4-7 sentences), simple language.\n"
        "4) If user asks for advice, refuse and redirect to educational info.\n"
    )

    # We use Responses API (recommended for new projects)
    response = client.responses.create(
        model="gpt-5.2",
        input=[
            {
                "role": "system",
                "content": system_instructions
            },
            {
                "role": "user",
                "content": (
                    f"User question: {message}\n\n"
                    f"Prototype simulated stock info:\n"
                    f"- ticker: {ticker}\n"
                    f"- last_price: {data['price']}\n"
                    f"- daily_change: {data['change']}\n"
                    f"- trend: {data['trend']}\n"
                    f"- volatility: {data['volatility']}\n\n"
                    "Answer as the chatbot."
                )
            }
        ],
    )

    return response.output_text.strip

# ---- 5) Gradio UI ----
demo = gr.ChatInterface(
    fn=chat_fn,
    title="StockSense (Prototype)",
    description=(
        "A conversational prototype for stock explanation (simulated data). "
        "Try: 'Summarize TSLA' / 'What are the risks of NVDA?' / 'Should I buy AAPL?'"
    ),
    
)

if __name__ == "__main__":
    demo.launch()