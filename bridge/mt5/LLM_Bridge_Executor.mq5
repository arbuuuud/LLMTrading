//+------------------------------------------------------------------+
//|                                       LLM_Bridge_Executor.mq5    |
//|                         Institutional AI Live Trading Bridge     |
//|                                  Copyright 2026, LLMTrading Core |
//+------------------------------------------------------------------+
#property copyright   "LLMTrading Core"
#property link        "https://github.com/alami/LLMTrading"
#property version     "1.01"
#property description "Lightweight TCP Bridge connecting MetaTrader 5 to Python Multi-Agent Brain"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--- INPUT PARAMETERS
input group "Bridge Server Settings"
input string   InpServerHost     = "127.0.0.1";  // Python Brain Host IP
input int      InpServerPort     = 5555;         // Python Brain Port
input int      InpTimeoutMs      = 3000;         // Socket Timeout (ms)
input ulong    InpMagicNumber    = 999001;       // Expert Magic Number
input ulong    InpDeviationPoints= 20;           // Max Slippage Deviation (points)

//--- GLOBAL VARIABLES
CTrade         m_trade;
CPositionInfo  m_position;
CAccountInfo   m_account;
int            m_socket          = INVALID_HANDLE;
bool           m_connected       = false;
ulong          m_last_connect_ms = 0;
datetime       m_last_heartbeat  = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(InpDeviationPoints);
   m_trade.SetTypeFilling(ORDER_FILLING_IOC);

   PrintFormat("[LLM Bridge] Initialized. Target Python Server: %s:%d (Magic: %I64u)", InpServerHost, InpServerPort, InpMagicNumber);
   
   ConnectToServer();
   EventSetTimer(1); // 1-second timer
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   DisconnectServer();
   PrintFormat("[LLM Bridge] Deinitialized (Reason: %d).", reason);
}

//+------------------------------------------------------------------+
//| Connect to Python TCP Server                                     |
//+------------------------------------------------------------------+
bool ConnectToServer()
{
   if(m_connected && m_socket != INVALID_HANDLE)
      return true;

   DisconnectServer();

   m_socket = SocketCreate();
   if(m_socket == INVALID_HANDLE)
   {
      PrintFormat("[LLM Bridge] Failed to create socket. Error: %d", GetLastError());
      return false;
   }

   PrintFormat("[LLM Bridge] Attempting connection to Python Server %s:%d...", InpServerHost, InpServerPort);

   if(!SocketConnect(m_socket, InpServerHost, InpServerPort, InpTimeoutMs))
   {
      int err = GetLastError();
      PrintFormat("[LLM Bridge] SocketConnect failed to %s:%d. Error: %d", InpServerHost, InpServerPort, err);
      SocketClose(m_socket);
      m_socket = INVALID_HANDLE;
      m_connected = false;
      return false;
   }

   m_connected = true;
   PrintFormat("[LLM Bridge] CONNECTED SUCCESSFULLY to Python Brain at %s:%d!", InpServerHost, InpServerPort);
   return true;
}

//+------------------------------------------------------------------+
//| Disconnect from Python Server                                    |
//+------------------------------------------------------------------+
void DisconnectServer()
{
   if(m_socket != INVALID_HANDLE)
   {
      SocketClose(m_socket);
      m_socket = INVALID_HANDLE;
   }
   m_connected = false;
}

//+------------------------------------------------------------------+
//| Send String Data over Socket                                     |
//+------------------------------------------------------------------+
bool SendString(string data)
{
   if(!m_connected || m_socket == INVALID_HANDLE)
      return false;

   uchar buffer[];
   int len = StringToCharArray(data, buffer) - 1; // Drop null terminator
   if(len <= 0)
      return false;

   int sent = SocketSend(m_socket, buffer, len);
   if(sent != len)
   {
      PrintFormat("[LLM Bridge] SocketSend failed. Sent %d of %d bytes. Error: %d", sent, len, GetLastError());
      DisconnectServer();
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Read Incoming Data from Python Brain                             |
//+------------------------------------------------------------------+
string ReadIncoming()
{
   if(!m_connected || m_socket == INVALID_HANDLE)
      return "";

   uint readable = SocketIsReadable(m_socket);
   if(readable <= 0)
      return "";

   uchar buffer[];
   ArrayResize(buffer, readable + 1);
   int received = SocketRead(m_socket, buffer, readable, InpTimeoutMs);
   if(received > 0)
   {
      buffer[received] = 0;
      return CharArrayToString(buffer);
   }
   return "";
}

//+------------------------------------------------------------------+
//| Simple JSON Value Extractor Helper                               |
//+------------------------------------------------------------------+
string ExtractJsonString(string json, string key)
{
   string search = "\"" + key + "\":\"";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos += StringLen(search);
   int end = StringFind(json, "\"", pos);
   if(end < 0) return "";
   return StringSubstr(json, pos, end - pos);
}

double ExtractJsonDouble(string json, string key)
{
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if(pos < 0) return 0.0;
   pos += StringLen(search);
   int end = pos;
   while(end < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, end);
      if(ch == ',' || ch == '}' || ch == '\n' || ch == '\r') break;
      end++;
   }
   return StringToDouble(StringSubstr(json, pos, end - pos));
}

//+------------------------------------------------------------------+
//| Process Order Command from Python                                |
//+------------------------------------------------------------------+
void ProcessCommand(string cmdJson)
{
   string action = ExtractJsonString(cmdJson, "action");
   if(action == "HEARTBEAT")
   {
      m_last_heartbeat = TimeCurrent();
      return;
   }

   if(action == "ORDER")
   {
      string symbol    = ExtractJsonString(cmdJson, "symbol");
      string side      = ExtractJsonString(cmdJson, "side");
      double lots      = ExtractJsonDouble(cmdJson, "lots");
      double sl        = ExtractJsonDouble(cmdJson, "sl");
      double tp        = ExtractJsonDouble(cmdJson, "tp");
      string comment   = ExtractJsonString(cmdJson, "comment");

      if(symbol == "") symbol = _Symbol;
      if(comment == "") comment = "LLM_AI_Trade";

      bool success = false;
      if(side == "BUY")
      {
         double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
         success = m_trade.Buy(lots, symbol, ask, sl, tp, comment);
      }
      else if(side == "SELL")
      {
         double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
         success = m_trade.Sell(lots, symbol, bid, sl, tp, comment);
      }

      // Send execution receipt back to Python
      string receipt = StringFormat(
         "{\"type\":\"ORDER_RECEIPT\",\"symbol\":\"%s\",\"side\":\"%s\",\"lots\":%.2f,\"success\":%s,\"ticket\":%I64u,\"retcode\":%d,\"deal\":%I64u,\"price\":%.2f}\n",
         symbol, side, lots, success ? "true" : "false",
         m_trade.ResultOrder(), m_trade.ResultRetcode(), m_trade.ResultDeal(), m_trade.ResultPrice()
      );
      SendString(receipt);
      PrintFormat("[LLM Bridge] Order %s %s %.2f -> Result: %s (Deal: %I64u, Price: %.2f)",
                  side, symbol, lots, success ? "OK" : "FAILED", m_trade.ResultDeal(), m_trade.ResultPrice());
   }
   else if(action == "CLOSE_ALL")
   {
      string symbol = ExtractJsonString(cmdJson, "symbol");
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         if(m_position.SelectByIndex(i))
         {
            if(m_position.Magic() == InpMagicNumber && (symbol == "" || m_position.Symbol() == symbol))
            {
               m_trade.PositionClose(m_position.Ticket());
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   if(!m_connected)
      return;

   double bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double spread = ask - bid;
   long   timeMs = (long)TimeCurrent() * 1000;

   // Count open positions for our Magic Number
   int openCount = 0;
   double totalUnrealized = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(m_position.SelectByIndex(i))
      {
         if(m_position.Magic() == InpMagicNumber && m_position.Symbol() == _Symbol)
         {
            openCount++;
            totalUnrealized += m_position.Profit();
         }
      }
   }

   // Format JSON tick payload
   string tickJson = StringFormat(
      "{\"type\":\"TICK\",\"symbol\":\"%s\",\"bid\":%.2f,\"ask\":%.2f,\"spread\":%.2f,\"time\":%I64d,\"equity\":%.2f,\"balance\":%.2f,\"open_positions\":%d,\"unrealized\":%.2f}\n",
      _Symbol, bid, ask, spread, timeMs,
      m_account.Equity(), m_account.Balance(), openCount, totalUnrealized
   );

   SendString(tickJson);

   // Check if Python sent back commands
   string response = ReadIncoming();
   if(response != "")
   {
      ProcessCommand(response);
   }
}

//+------------------------------------------------------------------+
//| Timer function (Heartbeat & Reconnect)                           |
//+------------------------------------------------------------------+
void OnTimer()
{
   ulong now_ms = GetTickCount64();
   if(!m_connected)
   {
      if(now_ms - m_last_connect_ms >= 3000)
      {
         m_last_connect_ms = now_ms;
         ConnectToServer();
      }
   }
   else
   {
      // Check for incoming commands during quiet periods
      string response = ReadIncoming();
      if(response != "")
      {
         ProcessCommand(response);
      }
   }
}
//+------------------------------------------------------------------+
