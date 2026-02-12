import os
import json
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import yfinance as yf
import logging

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


client = OpenAI(api_key=OPENAI_API_KEY)

DISCLAIMER = "**Disclaimer**: I am an AI prototype, not a licensed financial advisor. This report is for educational and research purposes only and does not constitute investment advice."

_data_cache = {}
CACHE_EXPIRY = 300  

# ============================================
# Smart Context Management
# ============================================

class SmartContextManager:
    """
    智能上下文管理器：
    1. 仅保留关键信息摘要（而非完整对话）
    2. 当股票切换时自动清空上下文
    3. 限制token使用
    """
    def __init__(self):
        self._contexts = {}  # {session_id: {"ticker": str, "summary": str, "last_intent": str}}

    def get_context(self, session_id: str, current_ticker: str) -> str:
        """获取上下文摘要"""
        if session_id not in self._contexts:
            return ""
        
        ctx = self._contexts[session_id]
        
        # 如果股票切换了，清空上下文
        if ctx.get("ticker") != current_ticker:
            self._contexts[session_id] = {"ticker": current_ticker, "summary": "", "last_intent": ""}
            return ""
        
        return ctx.get("summary", "")

    def update_context(self, session_id: str, ticker: str, user_msg: str, ai_response: str, intent: str):
        """更新上下文摘要（提取关键信息）主题和AI的核心结论"""

        summary_parts = []
        
        if session_id in self._contexts:
            old_summary = self._contexts[session_id].get("summary", "")
            if old_summary:
                summary_parts.append(old_summary)
        
        # 提取关键信息（避免保存整个对话）
        new_summary = f"User asked about {intent}: {user_msg[:50]}... AI noted: {ai_response[:100]}..."
        summary_parts.append(new_summary)
        
        # 只保留最近2条摘要
        summary = " | ".join(summary_parts[-2:])
        
        self._contexts[session_id] = {
            "ticker": ticker,
            "summary": summary,
            "last_intent": intent
        }

context_manager = SmartContextManager()

# ============================================
# Data Fetching Functions
# ============================================

def search_ticker_symbol(query: str) -> str:
    """Convert company name to ticker symbol"""
    query = query.strip().upper()
    if not query:
        return ""
    
    try:
        if query.isalpha() and len(query) <= 5:
            return query
        
        t = yf.Ticker(query)
        if t.info and 'symbol' in t.info:
            return t.info['symbol']
    except:
        pass
    
    return query

def get_historical_data(ticker: str, period: str = "1mo") -> List[Dict]:
    """获取历史价格数据用于绘图"""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        
        if hist.empty:
            return []
        
        # 转换为图表格式
        chart_data = []
        for date, row in hist.iterrows():
            chart_data.append({
                "date": date.strftime("%m/%d"),
                "close": round(row['Close'], 2),
                "volume": int(row['Volume'])
            })
        
        return chart_data
    except Exception as e:
        logger.error(f"Historical data error for {ticker}: {e}")
        return []

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
    """Get news and sentiment"""
    news_items = []
    sentiment = "Neutral"
    try:
        stock = yf.Ticker(ticker)
        raw_news = stock.news
        
        if raw_news:
            for item in raw_news[:5]:

                content = item.get('content', {})

                title = content.get('title', '')
                

                provider = content.get('provider', {})
                publisher = provider.get('displayName', 'Unknown')
                

                if title:
                    news_items.append({
                        'title': title,
                        'publisher': publisher,
            
                        'link': content.get('clickThroughUrl', {}).get('url', '')
                    })
        
        if news_items:
           
            text = " ".join([n['title'].lower() for n in news_items])
            
            
            
            if any(w in text for w in ['surge', 'jump', 'gain', 'profit', 'record', 'beat', 'grew', 'growth', 'rise', 'up']):
                sentiment = "Positive"
            
            elif any(w in text for w in ['drop', 'fall', 'loss', 'miss', 'crash', 'decline', 'down', 'slump', 'weak']):
                sentiment = "Negative"
                
    except Exception as e:
        logger.error(f"Error getting news sentiment: {e}")
        
    return news_items, sentiment

def get_comprehensive_data(ticker: str) -> Optional[Dict]:
    """Get comprehensive stock data with caching"""
    if not ticker:
        return None
    
    cache_key = f"{ticker}_data"
    if cache_key in _data_cache:
        data, timestamp = _data_cache[cache_key]
        if (datetime.now() - timestamp).seconds < CACHE_EXPIRY:
            return data

    try:
        stock = yf.Ticker(ticker)
        fast_info = stock.fast_info
        price = fast_info.last_price
        
        if price is None:
            return None
        
        info = {}
        try:
            info = stock.info
        except:
            pass

        news_items, sentiment = get_news_sentiment(ticker)
        news_str = "\n".join([f"- {n['title']} ({n['publisher']})" for n in news_items]) or "No recent news found."

        # 计算涨跌幅
        prev_close = fast_info.previous_close
        change_pct = ((price - prev_close) / prev_close) * 100 if prev_close else 0

        data = {
            "symbol": ticker.upper(),
            "name": info.get('longName', ticker),
            "price": f"${price:.2f}",
            "change_pct": f"{change_pct:+.2f}%",
            "sector": info.get('sector', 'N/A'),
            "industry": info.get('industry', 'N/A'),
            "pe": info.get('trailingPE', 'N/A'),
            "market_cap": info.get('marketCap', 'N/A'),
            "summary": info.get('longBusinessSummary', 'No description available.')[:500] + "...",
            "news_str": news_str,
            "sentiment": sentiment,
            "52w_high": info.get('fiftyTwoWeekHigh', 'N/A'),
            "52w_low": info.get('fiftyTwoWeekLow', 'N/A'),
        }
        
        _data_cache[cache_key] = (data, datetime.now())
        return data
        
    except Exception as e:
        logger.error(f"Data fetch error for {ticker}: {e}")
        return None

def should_include_chart(user_input: str, intent: str) -> bool:
    """判断是否需要返回图表"""
    chart_keywords = ['chart', 'graph', 'trend', 'price', 'history', 'performance', 'analysis', 'technical']
    
    # 如果是分析或建议类问题，默认附带图表
    if intent in ['analysis', 'advice']:
        return True
    
    # 如果用户明确提到图表相关词汇
    if any(keyword in user_input.lower() for keyword in chart_keywords):
        return True
    
    return False

def generate_ai_analysis(user_input: str, stock_data: Dict, intent: str, context: str) -> str:
    """Generate AI response with smart context"""
    
    context_note = f"\n### Previous Context:\n{context}" if context else ""

    system_prompt = f"""
You are a professional Financial Analyst Assistant.

### Current Analysis Object:
Stock: {stock_data['name']} ({stock_data['symbol']})
Price: {stock_data['price']} ({stock_data['change_pct']})
Sector: {stock_data['sector']} | Industry: {stock_data['industry']}

### Key Metrics:
- PE Ratio: {stock_data['pe']}
- Market Cap: {stock_data['market_cap']}
- 52-Week High/Low: {stock_data['52w_high']} / {stock_data['52w_low']}
- Market Sentiment: {stock_data['sentiment']}

### Recent News Headlines:
{stock_data['news_str']}
{context_note}

### Instructions:
- Answer the user's question directly and professionally
- Use Markdown formatting (###, **, -)
- If intent is ADVICE, you MUST include disclaimer at the end
- Be concise but informative
- Use bullet points for clarity when appropriate
- Reference news or metrics when relevant
"""
    
    # Let exceptions bubble up to the caller
    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ],
        temperature=0.7,
        max_tokens=800
    )
    return completion.choices[0].message.content


# 2. Helper function to create a structured fallback response
def generate_fallback_response(stock_data: Dict) -> str:
    """Generates a static response when AI is unavailable"""
    return f"""
⚠️ **AI Analysis Unavailable** (Connection Issue). 

Here is the live data for **{stock_data['name']} ({stock_data['symbol']})**:

### 📊 Market Data
- **Price:** {stock_data['price']}
- **Change:** {stock_data['change_pct']}
- **52-Week Range:** {stock_data['52w_low']} - {stock_data['52w_high']}

### 🏢 Fundamentals
- **Sector:** {stock_data['sector']}
- **Industry:** {stock_data['industry']}
- **Market Cap:** {stock_data['market_cap']}
- **P/E Ratio:** {stock_data['pe']}

### 📰 Recent News
{stock_data['news_str']}

---
*The AI brain is currently offline, but the market data above is real-time.*
"""




# ============================================
# API Routes
# ============================================

@app.route("/api/market_pulse", methods=["GET"])
def market_pulse():
    """获取市场概览数据"""
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
            c = ((p - pc) / pc) * 100
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
    Main chat endpoint with smart context, chart support, and Fallback mechanism
    """
    data = request.json
    raw_ticker = data.get("ticker", "").strip()
    user_message = data.get("message", "").strip()
    
    # Simple session ID (use proper auth in production)
    session_id = request.remote_addr
    
    if not raw_ticker:
        return jsonify({"response": "Please enter a **Ticker Symbol** or **Company Name** in the top bar first."})
    
    if not user_message:
        return jsonify({"response": "Please enter a specific question."})

    # 1. Normalize ticker
    ticker = search_ticker_symbol(raw_ticker)
    
    # 2. Get stock data (This must succeed to provide any value)
    stock_data = get_comprehensive_data(ticker)
    if not stock_data:
        return jsonify({"response": f"Could not find data for **{raw_ticker}**. Please check spelling or try a standard symbol (e.g. AAPL)."})

    # 3. Intent classification (Default to general if AI fails here)
    intent = "general"
    try:
        intent = classify_intent_with_ai(user_message)
    except Exception as e:
        logger.warning(f"Intent classification failed: {e}")
    
    # 4. Get smart context
    context = context_manager.get_context(session_id, ticker)
    
    # 5. Generate AI response (WITH FALLBACK)
    try:
        ai_response = generate_ai_analysis(user_message, stock_data, intent, context)
        
        # Update context only on success
        context_manager.update_context(session_id, ticker, user_message, ai_response, intent)
        
        # Add disclaimer if needed
        if intent == "advice":
            ai_response += f"\n\n---\n{DISCLAIMER}"
            
    except Exception as e:
        logger.error(f"AI Generation Failed: {e}")
        # SWITCH TO FALLBACK
        ai_response = generate_fallback_response(stock_data)

    # 6. Decide if chart should be included
    chart_data = None
    try:
        if should_include_chart(user_message, intent):
            chart_data = get_historical_data(ticker, period="1mo")
    except Exception as e:
        logger.warning(f"Chart generation failed: {e}")

    return jsonify({
        "response": ai_response,
        "ticker_display": f"{stock_data['name']} ({stock_data['symbol']})",
        "chart_data": chart_data
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000, host='0.0.0.0')
