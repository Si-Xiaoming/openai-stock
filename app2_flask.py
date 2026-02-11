import os
import json
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
import yfinance as yf
from functools import lru_cache
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "super_secret_key_for_session" # 用于 session 记忆

# ⚠ 环境变量读取API密钥
OPENAI_API_KEY = "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"
if not OPENAI_API_KEY:
    raise ValueError("请设置环境变量 OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---- Constants ----
DISCLAIMER = "⚠ **免责声明**: 我是AI原型，非持牌金融顾问。本报告仅供教育和研究目的，不构成投资建议。"

# 简单的内存缓存
_data_cache = {}
CACHE_EXPIRY = 300  # 5分钟

# ---- Memory Management (新功能: 记忆) ----
# 在真实生产环境中，应该使用 Redis 或数据库存储历史记录
class ConversationMemory:
    def __init__(self):
        self._memory = {} # {session_id: [{"role": "user", "content": ...}, ...]}

    def get_history(self, session_id: str, limit: int = 6) -> List[Dict]:
        return self._memory.get(session_id, [])[-limit:]

    def add_message(self, session_id: str, role: str, content: str):
        if session_id not in self._memory:
            self._memory[session_id] = []
        self._memory[session_id].append({"role": role, "content": content})
        # 限制历史长度，防止 token 爆炸
        if len(self._memory[session_id]) > 10:
             self._memory[session_id] = self._memory[session_id][-10:]

memory_store = ConversationMemory()

# ---- Helper Functions ----

def search_ticker_symbol(query: str) -> str:
    """
    如果用户输入的是公司名（如'Tesla'），尝试搜索对应的代码（'TSLA'）。
    如果看起来像代码，直接返回。
    """
    query = query.strip().upper()
    if not query:
        return ""
    
    # 简单的直接返回逻辑，如果以后需要支持中文搜索，可以接入 yfinance 的 Ticker Search
    # 或者调用 OpenAI 来做实体识别映射，这里为了速度使用 yfinance 的基础搜索
    try:
        # 如果是纯字母且长度小于6，假设是代码
        if query.isalpha() and len(query) <= 5:
            return query
        
        # 否则尝试搜索 (yfinance 的 search 功能较弱，这里模拟一个简单的逻辑)
        # 实际项目中建议使用专门的 Symbol Search API
        t = yf.Ticker(query)
        if t.info and 'symbol' in t.info:
            return t.info['symbol']
    except:
        pass
    
    return query # 默认返回原值尝试

def classify_intent_with_ai(user_text: str) -> str:
    """AI 意图分类"""
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
    """获取新闻和简单情感分析"""
    news_items = []
    sentiment = "中性"
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
        
        # 简单情感词匹配
        if news_items:
            text = " ".join([n['title'].lower() for n in news_items])
            if any(w in text for w in ['surge', 'jump', 'gain', 'profit', 'record']):
                sentiment = "偏积极"
            elif any(w in text for w in ['drop', 'fall', 'loss', 'miss', 'crash']):
                sentiment = "偏消极"
                
    except Exception as e:
        logger.error(f"News error: {e}")
        
    return news_items, sentiment

def get_comprehensive_data(ticker: str) -> Optional[Dict]:
    """获取综合股票数据 (带缓存)"""
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
        
        if price is None: return None # 代码无效
        
        info = {}
        try:
            info = stock.info
        except:
            pass # info 获取经常超时，做容错

        news_items, sentiment = get_news_sentiment(ticker)
        
        # 格式化新闻字符串供 Prompt 使用
        news_str = "\n".join([f"- {n['title']} ({n['publisher']})" for n in news_items]) or "暂无新闻"

        data = {
            "symbol": ticker.upper(),
            "name": info.get('longName', ticker),
            "price": f"${price:.2f}",
            "change_pct": f"{((price - fast_info.previous_close)/fast_info.previous_close)*100:+.2f}%",
            "sector": info.get('sector', 'N/A'),
            "industry": info.get('industry', 'N/A'),
            "pe": info.get('trailingPE', 'N/A'),
            "market_cap": info.get('marketCap', 'N/A'),
            "summary": info.get('longBusinessSummary', '暂无描述')[:500] + "...",
            "news_str": news_str,
            "sentiment": sentiment,
            "raw_news": news_items # 供前端展示链接用
        }
        
        _data_cache[cache_key] = (data, datetime.now())
        return data
        
    except Exception as e:
        logger.error(f"Data fetch error for {ticker}: {e}")
        return None

def generate_ai_analysis(user_input: str, stock_data: Dict, intent: str, history: List[Dict]) -> str:
    """生成 AI 回复，包含上下文记忆"""
    
    # 构建对话历史字符串
    history_str = ""
    for msg in history:
        role_name = "User" if msg['role'] == 'user' else "AI"
        history_str += f"{role_name}: {msg['content']}\n"

    system_prompt = f"""
    你是一位专业的金融分析师助手。
    
    ### 当前分析对象:
    股票: {stock_data['name']} ({stock_data['symbol']})
    价格: {stock_data['price']} ({stock_data['change_pct']})
    行业: {stock_data['sector']}
    
    ### 关键数据:
    PE: {stock_data['pe']}, 市值: {stock_data['market_cap']}
    市场新闻情感: {stock_data['sentiment']}
    新闻头条:
    {stock_data['news_str']}
    
    ### 任务:
    回答用户的具体问题。如果是ADVICE意图，必须包含免责声明。
    如果用户问的是上下文相关的问题（如"为什么下跌？"），请结合历史对话回答。
    
    ### 历史对话上下文:
    {history_str}
    
    请用Markdown格式回复，保持专业、客观。不要每次都重复所有数据，只回答用户关心的问题。
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
        return f"AI 分析出错: {e}"

# ---- Routes ----

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/market_pulse", methods=["GET"])
def market_pulse():
    # 简化的市场数据接口
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
    接收 JSON: { "ticker": "AAPL", "message": "风险如何？" }
    """
    data = request.json
    raw_ticker = data.get("ticker", "").strip()
    user_message = data.get("message", "").strip()
    
    # 简单的 Session ID 模拟 (基于 IP，实际应基于 Cookie/Token)
    session_id = request.remote_addr 
    
    if not raw_ticker:
        return jsonify({"response": "请先在上方输入框填写**股票代码**或**公司名称**。"})
    
    if not user_message:
        return jsonify({"response": "请输入您想询问的具体问题。"})

    # 1. 规范化 Ticker (如将 'Tesla' 转为 'TSLA')
    ticker = search_ticker_symbol(raw_ticker)
    
    # 2. 获取数据
    stock_data = get_comprehensive_data(ticker)
    if not stock_data:
        return jsonify({"response": f"❌ 找不到股票 **{raw_ticker}** 的数据，请检查拼写或尝试输入标准代码（如 AAPL）。"})

    # 3. 意图识别
    intent = classify_intent_with_ai(user_message)
    
    # 4. 获取历史记忆
    history = memory_store.get_history(session_id)
    
    # 5. 生成回复
    ai_response = generate_ai_analysis(user_message, stock_data, intent, history)
    
    # 6. 更新记忆
    # 保存当前的简要问答到历史，供下一轮使用
    memory_store.add_message(session_id, "user", f"关于 {ticker}: {user_message}")
    memory_store.add_message(session_id, "assistant", ai_response[:200] + "...") # 只存摘要防止上下文过长

    # 如果是建议类，强制加免责声明
    if intent == "advice":
        ai_response += f"\n\n---\n{DISCLAIMER}"

    return jsonify({
        "response": ai_response,
        "ticker_display": f"{stock_data['name']} ({stock_data['symbol']})" # 用于前端更新标题
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)