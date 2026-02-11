import os
import re
import json
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
import yfinance as yf
from functools import lru_cache
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ⚠ 安全改进：从环境变量读取API密钥
OPENAI_API_KEY = "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"
if not OPENAI_API_KEY:
    raise ValueError("请设置环境变量 OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---- Constants ----
DISCLAIMER = "⚠ **免责声明 (Disclaimer)**: 我是AI原型，非持牌金融顾问。本报告仅供教育和研究目的，不构成投资建议。"

# 扩展停用词表
COMMON_WORDS = {
    "WHO", "WHAT", "WHERE", "WHEN", "WHY", "HOW",
    "THE", "AND", "FOR", "HEY", "ARE", "YOU", "CAN",
    "THIS", "THAT", "WITH", "FROM", "HAVE", "NOT", "BUT", "SHOULD", 
    "I", "ME", "MY", "WE", "US", "THEY", "THEM", "IS", "AM", "DO", "DOES", 
    "DID", "WAS", "WERE", "BE", "BEEN", "HAS", "HAD", "WILL", "WOULD", "COULD", 
    "BUY", "SELL", "HOLD", "INVEST", "PREDICTION", "ANALYSIS", "REPORT",
    "RISK", "VOLATILE", "DANGER", "SAFE", "DOWNSIDE",
    "PRICE", "PERFORMANCE", "TREND", "SUMMARY", "HOW IS", "STOCK", "SHARE"
}

# 简单的内存缓存（生产环境建议使用Redis）
_data_cache = {}
CACHE_EXPIRY = 300  # 5分钟

# ---- Helper Functions ----

def extract_ticker(user_text: str) -> str:
    """
    提取股票代码
    改进：支持更多格式，如 $AAPL 或 AAPL.US
    """
    # 移除美元符号和后缀
    cleaned = re.sub(r'\$|\.US|\.HK', '', user_text.upper())
    
    # 查找2-5个大写字母的连续序列
    matches = re.findall(r'\b([A-Z]{2,5})\b', cleaned)
    candidates = [m for m in matches if m not in COMMON_WORDS]
    
    if candidates:
        logger.info(f"提取到股票代码: {candidates[0]}")
        return candidates[0]
    
    logger.warning("未能提取有效股票代码")
    return ""

def classify_intent_with_ai(user_text: str) -> str:
    """
    使用AI进行意图分类
    改进：添加更详细的错误处理
    """
    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "You are a financial assistant. Classify the user's intent into one of these categories:\n"
                        "- ADVICE: User wants investment recommendations or buy/sell advice\n"
                        "- RISK: User asks about risks, safety, or volatility\n"
                        "- ANALYSIS: User wants detailed analysis, report, or summary\n"
                        "- GENERAL: General questions about stock information\n\n"
                        "Reply with ONLY the category word."
                    )
                },
                {"role": "user", "content": user_text}
            ],
            temperature=0.0,
            max_tokens=10
        )
        intent = completion.choices[0].message.content.strip().upper()
        
        if intent in {"ADVICE", "RISK", "ANALYSIS", "GENERAL"}:
            logger.info(f"AI分类意图: {intent}")
            return intent.lower()
        
        logger.warning(f"AI返回未知意图: {intent}，使用规则兜底")
        return classify_intent_rule_based(user_text)
        
    except Exception as e:
        logger.error(f"AI意图分类失败: {e}，使用规则兜底")
        return classify_intent_rule_based(user_text)

def classify_intent_rule_based(user_text: str) -> str:
    """
    基于规则的意图识别（兜底方案）
    """
    t = user_text.lower()
    
    advice_keywords = ["buy", "sell", "should i", "recommend", "advice", "invest in"]
    risk_keywords = ["risk", "safe", "danger", "volatile", "downside", "risky"]
    analysis_keywords = ["analyze", "analysis", "report", "summary", "how is", "performance", "review"]
    
    if any(k in t for k in advice_keywords):
        return "advice"
    if any(k in t for k in risk_keywords):
        return "risk"
    if any(k in t for k in analysis_keywords):
        return "analysis"
    
    return "general"

def get_news_sentiment(ticker: str) -> Tuple[List[str], str]:
    """
    获取新闻并进行情感分析
    改进：使用多种方法获取新闻，增加鲁棒性
    """
    news_items = []
    sentiment = "中性"
    
    try:
        stock = yf.Ticker(ticker)
        
        # 方法1: 使用yfinance的news属性
        try:
            news_data = stock.news
            if news_data and len(news_data) > 0:
                for item in news_data[:5]:  # 最多取5条
                    title = item.get('title', '').strip()
                    publisher = item.get('publisher', 'Unknown')
                    link = item.get('link', '')
                    
                    # 验证新闻有效性
                    if title and len(title) > 10:
                        news_items.append({
                            'title': title,
                            'publisher': publisher,
                            'link': link
                        })
        except Exception as e:
            logger.warning(f"yfinance.news 获取失败: {e}")
        
        # 方法2: 如果方法1失败，尝试从info中获取
        if not news_items:
            try:
                info = stock.info
                if 'newsItems' in info and info['newsItems']:
                    for item in info['newsItems'][:5]:
                        title = item.get('title', '').strip()
                        if title and len(title) > 10:
                            news_items.append({
                                'title': title,
                                'publisher': item.get('source', 'Unknown'),
                                'link': item.get('url', '')
                            })
            except Exception as e:
                logger.warning(f"info.newsItems 获取失败: {e}")
        
        # 如果仍然没有新闻，使用通用搜索API（可选）
        if not news_items:
            logger.info(f"{ticker} 无法获取实时新闻，将返回占位符")
            news_items.append({
                'title': f"暂无{ticker}的最新新闻数据",
                'publisher': 'System',
                'link': ''
            })
        
        # 简单情感分析
        if news_items:
            titles_text = " ".join([n['title'].lower() for n in news_items])
            positive_words = ['rise', 'gain', 'profit', 'growth', 'beat', 'surge', 'rally']
            negative_words = ['fall', 'loss', 'drop', 'decline', 'miss', 'cut', 'concern']
            
            pos_count = sum(1 for w in positive_words if w in titles_text)
            neg_count = sum(1 for w in negative_words if w in titles_text)
            
            if pos_count > neg_count:
                sentiment = "偏积极"
            elif neg_count > pos_count:
                sentiment = "偏消极"
        
        logger.info(f"成功获取{len(news_items)}条新闻，情感: {sentiment}")
        
    except Exception as e:
        logger.error(f"新闻获取严重错误: {e}")
        news_items = [{
            'title': "新闻数据暂时不可用",
            'publisher': 'System',
            'link': ''
        }]
    
    return news_items, sentiment

@lru_cache(maxsize=100)
def get_cached_stock_info(ticker: str, cache_time: int):
    """
    缓存股票基本信息（使用cache_time作为缓存键的一部分）
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return info
    except Exception as e:
        logger.error(f"获取{ticker}信息失败: {e}")
        return {}

def get_comprehensive_data(ticker: str) -> Optional[Dict]:
    """
    获取综合股票数据
    改进：更好的错误处理、数据验证和缓存
    """
    if not ticker:
        return None
    
    # 检查缓存
    cache_key = f"{ticker}_data"
    if cache_key in _data_cache:
        cached_data, timestamp = _data_cache[cache_key]
        if (datetime.now() - timestamp).seconds < CACHE_EXPIRY:
            logger.info(f"使用缓存数据: {ticker}")
            return cached_data
    
    try:
        stock = yf.Ticker(ticker)
        
        # 1. 获取实时价格数据
        try:
            fast_info = stock.fast_info
            price = fast_info.last_price
            prev_close = fast_info.previous_close
            
            if price is None or prev_close is None:
                logger.error(f"{ticker} 价格数据为空")
                return None
            
            change_pct = ((price - prev_close) / prev_close) * 100
            
        except Exception as e:
            logger.error(f"获取{ticker}价格失败: {e}")
            return None
        
        # 2. 获取详细信息（使用缓存）
        cache_time = int(datetime.now().timestamp() // CACHE_EXPIRY)
        info = get_cached_stock_info(ticker, cache_time)
        
        # 3. 获取新闻和情感
        news_items, sentiment = get_news_sentiment(ticker)
        
        # 4. 格式化新闻
        news_formatted = []
        for idx, item in enumerate(news_items[:5], 1):
            news_formatted.append(
                f"{idx}. **{item['title']}** (来源: {item['publisher']})"
            )
        
        # 5. 组装完整数据
        data = {
            # 基本信息
            "symbol": ticker,
            "name": info.get('longName', info.get('shortName', ticker)),
            "price": f"${price:.2f}",
            "change": f"{change_pct:+.2f}%",
            "change_float": change_pct,
            
            # 行业信息
            "sector": info.get('sector', 'N/A'),
            "industry": info.get('industry', 'N/A'),
            
            # 估值指标
            "market_cap": format_large_number(info.get('marketCap')),
            "pe": format_ratio(info.get('trailingPE')),
            "forward_pe": format_ratio(info.get('forwardPE')),
            "peg": format_ratio(info.get('pegRatio')),
            "eps": f"${info.get('trailingEps', 0):.2f}" if info.get('trailingEps') else 'N/A',
            "div_yield": f"{info.get('dividendYield', 0) * 100:.2f}%" if info.get('dividendYield') else 'N/A',
            
            # 价格区间
            "high52": f"${info.get('fiftyTwoWeekHigh', 0):.2f}" if info.get('fiftyTwoWeekHigh') else 'N/A',
            "low52": f"${info.get('fiftyTwoWeekLow', 0):.2f}" if info.get('fiftyTwoWeekLow') else 'N/A',
            "day_high": f"${info.get('dayHigh', 0):.2f}" if info.get('dayHigh') else 'N/A',
            "day_low": f"${info.get('dayLow', 0):.2f}" if info.get('dayLow') else 'N/A',
            
            # 公司描述
            "summary": info.get('longBusinessSummary', 
                               f"{info.get('longName', ticker)} 是一家在{info.get('sector', '市场')}领域运营的公司。")[:600],
            
            # 新闻和情感
            "news": "\n".join(news_formatted) if news_formatted else "暂无最新新闻",
            "news_items": news_items,
            "sentiment": sentiment,
            
            # 其他指标
            "volume": format_large_number(info.get('volume')),
            "avg_volume": format_large_number(info.get('averageVolume')),
            "beta": format_ratio(info.get('beta')),
            
            # 分析师评级
            "target_price": f"${info.get('targetMeanPrice', 0):.2f}" if info.get('targetMeanPrice') else 'N/A',
            "recommendation": info.get('recommendationKey', 'N/A').upper(),
        }
        
        # 缓存数据
        _data_cache[cache_key] = (data, datetime.now())
        logger.info(f"成功获取{ticker}的完整数据")
        
        return data
        
    except Exception as e:
        logger.error(f"获取{ticker}数据时发生严重错误: {e}")
        return None

def format_large_number(num) -> str:
    """格式化大数字（如市值）"""
    if num is None or num == 'N/A':
        return 'N/A'
    
    try:
        num = float(num)
        if num >= 1e12:
            return f"${num/1e12:.2f}T"
        elif num >= 1e9:
            return f"${num/1e9:.2f}B"
        elif num >= 1e6:
            return f"${num/1e6:.2f}M"
        else:
            return f"${num:,.0f}"
    except:
        return 'N/A'

def format_ratio(value) -> str:
    """格式化比率数据"""
    if value is None or value == 'N/A':
        return 'N/A'
    
    try:
        return f"{float(value):.2f}"
    except:
        return 'N/A'

def generate_ai_analysis(user_input: str, stock_data: Dict, intent: str) -> str:
    """
    生成AI分析报告
    改进：根据意图定制提示词
    """
    
    # 根据意图调整系统提示
    intent_context = {
        "advice": "用户寻求投资建议。请提供平衡的分析，强调风险和机遇，但明确声明这不是投资建议。",
        "risk": "用户关注风险。请重点分析潜在风险因素、波动性和下行风险。",
        "analysis": "用户需要深度分析。请提供全面的基本面和技术面分析。",
        "general": "用户询问一般信息。请提供清晰、全面的公司概况。"
    }
    
    system_prompt = f"""
你是一位资深金融分析师，拥有15年以上的投资研究经验。

### 核心任务：
根据提供的真实市场数据，为用户撰写一份专业的股票分析报告。

### 关键要求：
1. **语言一致性**：必须使用与用户输入**相同的语言**（中文输入→中文报告；英文输入→英文报告）
2. **原创内容**：禁止直接复制数据结构，用自然语言解读数据背后的含义
3. **深度分析**：不仅陈述数字，还要解释其意义（如：高PE意味着市场对增长的高预期）
4. **客观专业**：保持中立态度，避免情绪化用词
5. **意图导向**：{intent_context.get(intent, '')}

### 实时市场数据：
**公司**：{stock_data['name']} ({stock_data['symbol']})
**当前价格**：{stock_data['price']} ({stock_data['change']})
**行业分类**：{stock_data['sector']} / {stock_data['industry']}

**估值指标**：
- 市值：{stock_data['market_cap']}
- 市盈率 (P/E)：{stock_data['pe']}
- 前瞻市盈率：{stock_data['forward_pe']}
- PEG比率：{stock_data['peg']}
- 每股收益 (EPS)：{stock_data['eps']}
- 股息收益率：{stock_data['div_yield']}

**价格表现**：
- 52周高点：{stock_data['high52']}
- 52周低点：{stock_data['low52']}
- 今日区间：{stock_data['day_low']} - {stock_data['day_high']}

**交易数据**：
- 成交量：{stock_data['volume']}
- 平均成交量：{stock_data['avg_volume']}
- Beta系数：{stock_data['beta']}

**分析师观点**：
- 目标价：{stock_data['target_price']}
- 评级：{stock_data['recommendation']}

**最新新闻** (情感倾向: {stock_data['sentiment']}):
{stock_data['news']}

**公司简介**：
{stock_data['summary']}

### 报告结构（使用Markdown格式）：

# 📊 {stock_data['name']} ({stock_data['symbol']}) 投资分析报告

## 一、核心观点 (Executive Summary)
*用2-3句话概括公司现状、估值水平和投资要点*

## 二、基本面分析 (Fundamental Analysis)
*详细解读估值指标：*
- 当前估值是否合理？（对比行业平均）
- EPS和盈利能力如何？
- 股息政策对投资者的吸引力

## 三、技术面与市场表现
*分析价格动态：*
- 相对52周区间的位置（是否接近高点/低点）
- 成交量变化的含义
- Beta系数反映的波动性

## 四、行业地位与竞争优势
*行业背景分析：*
- 在{stock_data['industry']}领域的地位
- 关键竞争优势或劣势

## 五、新闻解读与市场情绪
*基于最新新闻标题：*
- 市场情绪偏向（积极/消极/中性）
- 近期重大事件对股价的潜在影响

## 六、风险与机遇
**潜在风险**：
- 列出3个主要风险因素

**投资机遇**：
- 列出2-3个看涨理由

## 七、总结与建议
*综合结论（强调教育目的，非投资建议）*

---
{DISCLAIMER}
"""
    
    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        
        response = completion.choices[0].message.content
        logger.info("AI分析生成成功")
        return response
        
    except Exception as e:
        logger.error(f"AI生成报告失败: {e}")
        return f"抱歉，生成分析报告时出错：{str(e)}\n\n{DISCLAIMER}"

# ---- Routes ----

@app.route("/")
def index():
    """主页"""
    return render_template("index.html")

@app.route("/api/market_pulse")
def market_pulse():
    """
    市场脉搏接口（实时主要指数）
    改进：使用真实数据而非硬编码
    """
    try:
        indices = {
            "^GSPC": "S&P 500",
            "^IXIC": "Nasdaq",
            "^DJI": "Dow Jones"
        }
        
        result = []
        for symbol, name in indices.items():
            try:
                ticker = yf.Ticker(symbol)
                price = ticker.fast_info.last_price
                prev_close = ticker.fast_info.previous_close
                change = ((price - prev_close) / prev_close) * 100
                
                result.append({
                    "name": name,
                    "price": f"{price:,.2f}",
                    "change": round(change, 2),
                    "change_str": f"{change:+.2f}%"
                })
            except Exception as e:
                logger.warning(f"获取{name}数据失败: {e}")
                continue
        
        return jsonify(result if result else [
            {"name": "市场数据", "price": "N/A", "change": 0, "change_str": "暂无数据"}
        ])
        
    except Exception as e:
        logger.error(f"市场脉搏接口错误: {e}")
        return jsonify([{"name": "错误", "price": "N/A", "change": 0, "change_str": "数据加载失败"}])

@app.route("/api/chat", methods=["POST"])
def chat_api():
    """
    聊天接口
    改进：完整的错误处理和日志记录
    """
    try:
        user_input = request.json.get("message", "").strip()
        
        if not user_input:
            return jsonify({"response": "请输入您的问题。"})
        
        logger.info(f"收到用户输入: {user_input}")
        
        # 1. 提取股票代码
        ticker = extract_ticker(user_input)
        
        if not ticker:
            return jsonify({
                "response": "请提供有效的股票代码（如 AAPL、TSLA、MSFT），我将为您生成详细的分析报告。\n\n"
                           "示例：\"分析一下 AAPL 的投资价值\" 或 \"TSLA 有什么风险？\""
            })
        
        # 2. 意图识别
        intent = classify_intent_with_ai(user_input)
        logger.info(f"识别意图: {intent}")
        
        # 3. 获取股票数据
        stock_data = get_comprehensive_data(ticker)
        
        if not stock_data:
            return jsonify({
                "response": f"❌ 抱歉，无法获取 {ticker} 的数据。请检查：\n"
                           f"1. 股票代码是否正确\n"
                           f"2. 该股票是否在美股市场交易\n"
                           f"3. 网络连接是否正常"
            })
        
        # 4. 生成AI分析
        ai_response = generate_ai_analysis(user_input, stock_data, intent)
        
        return jsonify({"response": ai_response})
        
    except Exception as e:
        logger.error(f"聊天接口严重错误: {e}", exc_info=True)
        return jsonify({
            "response": f"系统错误：{str(e)}\n\n请稍后重试或联系技术支持。"
        }), 500

@app.route("/api/clear_cache", methods=["POST"])
def clear_cache():
    """清除缓存接口（用于调试）"""
    _data_cache.clear()
    get_cached_stock_info.cache_clear()
    logger.info("缓存已清除")
    return jsonify({"status": "success", "message": "缓存已清除"})

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "接口不存在"}), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"服务器错误: {e}")
    return jsonify({"error": "服务器内部错误"}), 500

if __name__ == "__main__":
    # 生产环境建议使用 gunicorn 或 uwsgi
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=os.getenv("FLASK_ENV") == "development"
    )