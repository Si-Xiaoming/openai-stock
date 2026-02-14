import React, { useState, useEffect, useRef } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, AreaChart, Area } from 'recharts';
import { Send, TrendingUp, Shield, Lightbulb, Globe, Mic } from 'lucide-react';

const API_BASE = 'http://localhost:5000';

export default function App() {
  const [ticker, setTicker] = useState('AAPL');
  const [messages, setMessages] = useState([
    { role: 'bot', content: 'Hello! I am your AI Financial Assistant.\nPlease confirm the stock ticker at the top left (default is AAPL), then enter your question below.' }
  ]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [marketData, setMarketData] = useState([]);
  const [statusText, setStatusText] = useState('👈 Please enter target stock here');
  const [chartData, setChartData] = useState(null);
  const [isRecording, setIsRecording] = useState(false);
  
  const chatBoxRef = useRef(null);
  const recognitionRef = useRef(null);


  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.lang = 'en-US';
      recognition.interimResults = false;

      recognition.onstart = () => {
        setIsRecording(true);
      };
      
      recognition.onend = () => {
        setIsRecording(false);
        // need to be checked by user
      };
      
      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        setInputValue(transcript);
      };
      
      recognition.onerror = (event) => {
        console.error('Speech error:', event.error);
        setIsRecording(false);
        if (event.error === 'not-allowed') {
          alert('Microphone access denied. Please enable microphone permissions.');
        }
      };

      recognitionRef.current = recognition;
    }
    
    // 清理函数
    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.abort();
      }
    };
  }, []); // 空依赖数组，只在组件挂载时运行一次

  // 加载市场数据
  useEffect(() => {
    loadMarketPulse();
  }, []);

  // 自动滚动聊天框
  useEffect(() => {
    if (chatBoxRef.current) {
      chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight;
    }
  }, [messages]);

  const loadMarketPulse = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/market_pulse`);
      const data = await res.json();
      setMarketData(data);
    } catch (error) {
      console.error('Failed to load market data:', error);
    }
  };

  const toggleRecording = () => {
    if (!recognitionRef.current) {
      alert('Voice input not supported in this browser (try Chrome/Edge).');
      return;
    }
    if (isRecording) {
      recognitionRef.current.stop();
    } else {
      recognitionRef.current.start();
    }
  };

  const sendQuickAsk = (type) => {
    const prompts = {
      'analysis': 'Please generate a detailed deep analysis report for me, including fundamentals and technicals with price chart.',
      'risk': 'What are the main risks of investing in this stock right now? Is it safe?',
      'advice': 'Is the current price suitable for buying or selling? Please provide analysis basis with chart.',
      'general': 'What does this company mainly do? Any recent big news?'
    };
    setInputValue(prompts[type]);
    setTimeout(() => handleSendMessage(prompts[type]), 100);
  };

  const handleSendMessage = async (messageOverride) => {
    const message = messageOverride || inputValue.trim();
    if (!ticker.trim()) {
      alert('Please enter a stock ticker at the top first (e.g., AAPL)');
      return;
    }
    if (!message) return;

    // 添加用户消息
    setMessages(prev => [...prev, { role: 'user', content: message }]);
    setInputValue('');
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, message })
      });
      const data = await res.json();

      if (data.ticker_display) {
        setStatusText(`Analyzing: ${data.ticker_display}`);
      }

      // 添加AI消息
      setMessages(prev => [...prev, { 
        role: 'bot', 
        content: data.response,
        chartData: data.chart_data 
      }]);

      // 如果有图表数据，保存
      if (data.chart_data) {
        setChartData(data.chart_data);
      }

    } catch (error) {
      setMessages(prev => [...prev, { 
        role: 'bot', 
        content: '❌ Connection failed. Please check your network.' 
      }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-slate-900 text-slate-50">
      {/* Sidebar */}
      <div className="w-64 bg-slate-800 border-r border-slate-700 p-5 flex flex-col gap-5">
        <div className="text-xl font-bold text-blue-500 flex items-center gap-2">
          ⚡ Stock-Elf
        </div>

        {/* Market Pulse */}
        <div>
          <div className="text-xs uppercase text-slate-400 font-bold mb-3">Market Pulse</div>
          {marketData.map((item, idx) => (
            <div key={idx} className="flex justify-between bg-white/5 p-2.5 rounded-lg mb-2 text-sm">
              <span>{item.name}</span>
              <div className="text-right">
                <div>{item.price}</div>
                <div className={`text-xs ${item.change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {item.change_str}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Quick Ask Buttons */}
        <div>
          <div className="text-xs uppercase text-slate-400 font-bold mb-3">Quick Ask</div>
          <button onClick={() => sendQuickAsk('analysis')} className="quick-btn">
            <TrendingUp size={18} /> Deep Analysis Report
          </button>
          <button onClick={() => sendQuickAsk('risk')} className="quick-btn">
            <Shield size={18} /> Risk Assessment
          </button>
          <button onClick={() => sendQuickAsk('advice')} className="quick-btn">
            <Lightbulb size={18} /> Investment Advice
          </button>
          <button onClick={() => sendQuickAsk('general')} className="quick-btn">
            <Globe size={18} /> Company Overview
          </button>
        </div>
      </div>

      {/* Main Area */}
      <div className="flex-1 flex flex-col">
        {/* Ticker Bar */}
        <div className="p-4 bg-slate-800 border-b border-slate-700 flex items-center gap-4">
          <div className="flex items-center bg-slate-900 border border-blue-500 rounded-lg px-3 py-1.5 w-80">
            <span className="text-sm text-blue-500 font-bold mr-3">STOCK:</span>
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              className="bg-transparent border-none text-white font-bold w-full outline-none uppercase"
              placeholder="Ticker/Name (e.g. AAPL)"
            />
          </div>
          <div className="text-sm text-slate-400">{statusText}</div>
        </div>

        {/* Chat Area */}
        <div ref={chatBoxRef} className="flex-1 overflow-y-auto p-5 space-y-5">
          {messages.map((msg, idx) => (
            <div key={idx}>
              <div className={`message ${msg.role === 'bot' ? 'msg-bot' : 'msg-user'}`}>
                <MessageContent content={msg.content} />
              </div>
              {msg.chartData && <StockChart data={msg.chartData} />}
            </div>
          ))}
        </div>

        {/* Input Area */}
        <div className="p-5 bg-slate-800 border-t border-slate-700">
          {loading && <div className="text-slate-400 text-sm mb-2 ml-2">AI is analyzing data...</div>}
          {isRecording && <div className="text-red-400 text-sm mb-2 ml-2 flex items-center gap-2">
            Listening... Speak your question
          </div>}
          <div className="flex gap-3 bg-slate-700 p-3 rounded-xl items-center">
            <button
              onClick={toggleRecording}
              className={`mic-btn ${isRecording ? 'recording' : ''}`}
              title={isRecording ? "Stop Recording" : "Voice Input (Click to speak)"}
            >
              <Mic size={20} />
            </button>
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && !loading && handleSendMessage()}
              className="flex-1 bg-transparent border-none text-white outline-none"
              placeholder={isRecording ? "Listening..." : "Type your question or click 🎤 to speak..."}
              disabled={isRecording}
            />
            <button
              onClick={() => handleSendMessage()}
              disabled={loading || isRecording}
              className="send-btn"
            >
              <Send size={18} />
            </button>
          </div>
        </div>
      </div>

      <style jsx>{`
        .quick-btn {
          width: 100%;
          display: flex;
          align-items: center;
          gap: 8px;
          background: transparent;
          border: 1px solid rgb(51, 65, 85);
          color: rgb(203, 213, 225);
          padding: 12px;
          border-radius: 8px;
          margin-bottom: 8px;
          cursor: pointer;
          transition: all 0.2s;
          font-size: 0.9rem;
        }
        .quick-btn:hover {
          background: rgba(255,255,255,0.05);
          border-color: rgb(59, 130, 246);
          color: white;
        }
        .message {
          max-width: 80%;
          padding: 15px;
          border-radius: 12px;
          line-height: 1.6;
          font-size: 0.95rem;
        }
        .msg-bot {
          align-self: flex-start;
          background: rgb(30, 41, 59);
          border-bottom-left-radius: 2px;
          border: 1px solid rgb(51, 65, 85);
        }
        .msg-user {
          align-self: flex-end;
          background: rgb(37, 99, 235);
          border-bottom-right-radius: 2px;
          margin-left: auto;
        }
        .send-btn {
          background: rgb(59, 130, 246);
          color: white;
          border: none;
          padding: 8px 20px;
          border-radius: 8px;
          cursor: pointer;
          font-weight: bold;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .send-btn:disabled {
          background: rgb(100, 116, 139);
        }
        .mic-btn {
          background: transparent;
          border: none;
          color: rgb(148, 163, 184);
          cursor: pointer;
          padding: 4px;
          transition: all 0.2s;
          display: flex;
          align-items: center;
        }
        .mic-btn:hover {
          color: white;
          transform: scale(1.1);
        }
        .mic-btn.recording {
          color: rgb(239, 68, 68);
          animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.2); opacity: 0.8; }
        }
      `}</style>
    </div>
  );
}

// Message Content Component with Markdown support
function MessageContent({ content }) {
  return (
    <div className="prose prose-invert prose-sm max-w-none">
      {content.split('\n').map((line, i) => {
        // Simple markdown parsing
        if (line.startsWith('###')) {
          return <h3 key={i} className="text-blue-400 text-lg mt-3 mb-2">{line.replace('###', '').trim()}</h3>;
        }
        if (line.startsWith('##')) {
          return <h2 key={i} className="text-blue-400 text-xl mt-3 mb-2">{line.replace('##', '').trim()}</h2>;
        }
        if (line.startsWith('- ')) {
          return <li key={i} className="ml-5">{line.replace('- ', '').trim()}</li>;
        }
        if (line.includes('**')) {
          const parts = line.split('**');
          return (
            <p key={i} className="my-2">
              {parts.map((part, j) => j % 2 === 1 ? <strong key={j}>{part}</strong> : part)}
            </p>
          );
        }
        return line ? <p key={i} className="my-2">{line}</p> : <br key={i} />;
      })}
    </div>
  );
}

// Stock Chart Component
function StockChart({ data }) {
  if (!data || data.length === 0) return null;

  return (
    <div className="mt-4 p-4 bg-slate-800 rounded-lg border border-slate-700">
      <h3 className="text-blue-400 text-sm font-bold mb-3">📈 Price Trend (Last 30 Days)</h3>
      <ResponsiveContainer width="100%" height={250}>
        <AreaChart data={data}>
          <defs>
            <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8}/>
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="date" stroke="#94a3b8" style={{ fontSize: '12px' }} />
          <YAxis stroke="#94a3b8" style={{ fontSize: '12px' }} domain={['auto', 'auto']} />
          <Tooltip 
            contentStyle={{ 
              backgroundColor: '#1e293b', 
              border: '1px solid #334155',
              borderRadius: '8px',
              color: '#f8fafc'
            }} 
          />
          <Area 
            type="monotone" 
            dataKey="close" 
            stroke="#3b82f6" 
            strokeWidth={2}
            fillOpacity={1} 
            fill="url(#colorPrice)" 
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}