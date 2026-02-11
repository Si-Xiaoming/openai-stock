import os
import json
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
import yfinance as yf
from functools import lru_cache
import logging

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "super_secret_key_for_session" # For session memory

# ⚠ API Key from Environment Variable
OPENAI_API_KEY = "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"
if not OPENAI_API_KEY:
    raise ValueError("Please set the OPENAI_API_KEY environment variable.")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---- Constants ----
DISCLAIMER = "⚠ **Disclaimer**: I am an AI prototype, not a licensed financial advisor. This report is for educational and research purposes only and does not constitute investment advice."

# Simple In-Memory Cache
_data_cache = {}
CACHE_EXPIRY = 300  # 5 minutes

# ---- Memory Management (New Feature: Context Memory) ----
# In a production environment, use Redis or a database.
class ConversationMemory:
    def __init__(self):
        self._memory = {} # {session_id: [{"role": "user", "content": ...}, ...]}

    def get_history(self, session_id: str, limit: int = 6) -> List[Dict]:
        return self._memory.get(session_id, [])[-limit:]

    def add_message(self, session_id: str, role: str, content: str):
        if session_id not in self._memory:
            self._memory[session_id] = []
        self._memory[session_id].append({"role": role, "content": content})
        # Limit history length to prevent token explosion
        if len(self._memory[session_id]) > 10:
             self._memory[session_id] = self._memory[session_id][-10:]

memory_store = ConversationMemory()

# ---- Helper Functions ----

def search_ticker_symbol(query: str) -> str:
    """
    If user enters a company name (e.g. 'Tesla'), try to find the symbol ('TSLA').
    If it looks like a ticker, return it directly.
    """
    query = query.strip().upper()
    if not query:
        return ""
    
    try:
        # If alphabetic and short, assume it's a ticker
        if query.isalpha() and len(query) <= 5:
            return query
        
        # Otherwise try a simple search via yfinance
        t = yf.Ticker(query)
        if t.info and 'symbol' in t.info:
            return t.info['symbol']
    except:
        pass
    
    return query # Default to returning original query

def classify_intent_with_ai(user_text: str) -> str:
    """AI Intent Classification"""
    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Classify intent: ADVICE (buy/sell), RISK (safety/danger), ANALYSIS (report/deep dive), GENERAL (info). Reply ONLY the category word."},
                {"role": "user", "content": user_text}
            ],
            temperature=0.0,
            max_tokens=10
        )
        intent = completion.choices[0].message.content.strip().upper()
        return intent.lower() if intent in {"ADVICE", "RISK", "ANALYSIS", "GENERAL"} else "general"
    except:
        return "general"

def get_news_sentiment(ticker: str) -> Tuple[List[Dict], str]:
    """Get news and simple sentiment analysis"""
    news_items = []
    sentiment = "Neutral"
    try:
        stock = yf.Ticker(ticker)
        raw_news = stock.news
        if raw_news:
            for item in raw_news[:3]:
                news_items.append({
                    'title': item.get('title', ''),
                    'publisher': item.get('publisher', 'Unknown'),
                    'link': item.get('link', '#')
                })
        
        # Simple sentiment keyword matching
        if news_items:
            text = " ".join([n['title'].lower() for n in news_items])
            if any(w in text for w in ['surge', 'jump', 'gain', 'profit', 'record']):
                sentiment = "Positive"
            elif any(w in text for w in ['drop', 'fall', 'loss', 'miss', 'crash']):
                sentiment = "Negative"
                
    except Exception as e:
        logger.error(f"News error: {e}")
        
    return news_items, sentiment

def get_comprehensive_data(ticker: str) -> Optional[Dict]:
    """Get comprehensive stock data (with caching)"""
    if not ticker: return None
    
    cache_key = f"{ticker}_data"
    if cache_key in _data_cache:
        data, timestamp = _data_cache[cache_key]
        if (datetime.now() - timestamp).seconds < CACHE_EXPIRY:
            return data

    try:
        stock = yf.Ticker(ticker)
        fast_info = stock.fast_info
        price = fast_info.last_price
        
        if price is None: return None # Invalid ticker
        
        info = {}
        try:
            info = stock.info
        except:
            pass # info fetch often times out, fail gracefully

        news_items, sentiment = get_news_sentiment(ticker)
        
        # Format news string for Prompt
        news_str = "\n".join([f"- {n['title']} ({n['publisher']})" for n in news_items]) or "No recent news found."

        data = {
            "symbol": ticker.upper(),
            "name": info.get('longName', ticker),
            "price": f"${price:.2f}",
            "change_pct": f"{((price - fast_info.previous_close)/fast_info.previous_close)*100:+.2f}%",
            "sector": info.get('sector', 'N/A'),
            "industry": info.get('industry', 'N/A'),
            "pe": info.get('trailingPE', 'N/A'),
            "market_cap": info.get('marketCap', 'N/A'),
            "summary": info.get('longBusinessSummary', 'No description available.')[:500] + "...",
            "news_str": news_str,
            "sentiment": sentiment,
            "raw_news": news_items # For frontend display
        }
        
        _data_cache[cache_key] = (data, datetime.now())
        return data
        
    except Exception as e:
        logger.error(f"Data fetch error for {ticker}: {e}")
        return None

def generate_ai_analysis(user_input: str, stock_data: Dict, intent: str, history: List[Dict]) -> str:
    """Generate AI response with context memory"""
    
    # Build conversation history string
    history_str = ""
    for msg in history:
        role_name = "User" if msg['role'] == 'user' else "AI"
        history_str += f"{role_name}: {msg['content']}\n"

    system_prompt = f"""
    You are a professional Financial Analyst Assistant.
    
    ### Current Analysis Object:
    Stock: {stock_data['name']} ({stock_data['symbol']})
    Price: {stock_data['price']} ({stock_data['change_pct']})
    Sector: {stock_data['sector']}
    
    ### Key Data:
    PE Ratio: {stock_data['pe']}, Market Cap: {stock_data['market_cap']}
    Market Sentiment: {stock_data['sentiment']}
    News Headlines:
    {stock_data['news_str']}
    
    ### Task:
    Answer the user's specific question. If the intent is ADVICE, you MUST include a disclaimer.
    If the user asks context-dependent questions (e.g., "Why did it drop?"), answer based on the conversation history.
    
    ### Conversation History Context:
    {history_str}
    
    Please reply in **English** using Markdown format. Keep it professional and objective. Do not repeat all data every time; answer only what the user cares about.
    """
    
    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.7
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"AI Analysis Error: {e}"

# ---- Routes ----

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/market_pulse", methods=["GET"])
def market_pulse():
    # Simplified market data interface
    indices = [
        {"symbol": "^GSPC", "name": "S&P 500"},
        {"symbol": "^IXIC", "name": "Nasdaq"},
        {"symbol": "BTC-USD", "name": "Bitcoin"}
    ]
    result = []
    for idx in indices:
        try:
            t = yf.Ticker(idx["symbol"])
            p = t.fast_info.last_price
            pc = t.fast_info.previous_close
            c = ((p-pc)/pc)*100
            result.append({
                "name": idx["name"], 
                "price": f"{p:,.0f}", 
                "change": c, 
                "change_str": f"{c:+.2f}%"
            })
        except:
            pass
    return jsonify(result)

@app.route("/api/chat", methods=["POST"])
def chat_api():
    """
    Receives JSON: { "ticker": "AAPL", "message": "What are the risks?" }
    """
    data = request.json
    raw_ticker = data.get("ticker", "").strip()
    user_message = data.get("message", "").strip()
    
    # Simple Session ID (based on IP, use Cookie/Token in production)
    session_id = request.remote_addr 
    
    if not raw_ticker:
        return jsonify({"response": "Please enter a **Ticker Symbol** or **Company Name** in the top bar first."})
    
    if not user_message:
        return jsonify({"response": "Please enter a specific question."})

    # 1. Normalize Ticker (e.g. 'Tesla' -> 'TSLA')
    ticker = search_ticker_symbol(raw_ticker)
    
    # 2. Get Data
    stock_data = get_comprehensive_data(ticker)
    if not stock_data:
        return jsonify({"response": f"❌ Could not find data for **{raw_ticker}**. Please check spelling or try a standard symbol (e.g. AAPL)."})

    # 3. Intent Recognition
    intent = classify_intent_with_ai(user_message)
    
    # 4. Get History
    history = memory_store.get_history(session_id)
    
    # 5. Generate Response
    ai_response = generate_ai_analysis(user_message, stock_data, intent, history)
    
    # 6. Update Memory
    memory_store.add_message(session_id, "user", f"About {ticker}: {user_message}")
    memory_store.add_message(session_id, "assistant", ai_response[:200] + "...") # Store summary only

    # If advice intent, force disclaimer
    if intent == "advice":
        ai_response += f"\n\n---\n{DISCLAIMER}"

    return jsonify({
        "response": ai_response,
        "ticker_display": f"{stock_data['name']} ({stock_data['symbol']})" # For frontend title update
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)