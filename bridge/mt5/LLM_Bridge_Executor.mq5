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

//--- INPUT PARAMETERS (ZERO-CONFIG RISK: GOVERNED BY PYTHON WEB DASHBOARD)
input group "=== LLM Trading Bridge Connection ==="
input string   InpServerHost     = "127.0.0.1";  // Python Brain Host IP
input int      InpServerPort     = 5555;         // Python Brain Port
input int      InpTimeoutMs      = 3000;         // Socket Timeout (ms)
input ulong    InpDeviationPoints= 20;           // Max Slippage Deviation (points)
input ulong    InpMagicNumber    = 1001;         // Default Expert Magic Number
input int      InpSyncBars       = 360;          // Historical Bars to Sync on Reconnect (Default: 360 = 6 hours)
input group "=== Note: Risk Management is 100% Handled via Dashboard ==="

//--- GLOBAL VARIABLES
CTrade         m_trade;
CPositionInfo  m_position;
CAccountInfo   m_account;
int            m_socket          = INVALID_HANDLE;
bool           m_connected       = false;
ulong          m_last_connect_ms = 0;
datetime       m_last_heartbeat  = 0;
ulong          m_last_timer_ms   = 0;
string         m_incoming_buffer = "";

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   m_trade.SetExpertMagicNumber(1001);
   m_trade.SetDeviationInPoints(InpDeviationPoints);

   // Configure dynamic filling mode based on broker/symbol capabilities
   uint filling = (uint)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_FOK) != 0)
      m_trade.SetTypeFilling(ORDER_FILLING_FOK);
   else if((filling & SYMBOL_FILLING_IOC) != 0)
      m_trade.SetTypeFilling(ORDER_FILLING_IOC);
   else
      m_trade.SetTypeFilling(ORDER_FILLING_RETURN);

   PrintFormat("[LLM Bridge] Initialized. Account: %I64d (%s). Brain: %s:%d",
               AccountInfoInteger(ACCOUNT_LOGIN), AccountInfoString(ACCOUNT_COMPANY), InpServerHost, InpServerPort);
   
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
   Sleep(50); // Allow OS/Wine socket buffers to settle before first send

   // Send Registration Handshake with Account Details
   string regJson = StringFormat(
      "{\"type\":\"REGISTER\",\"account_id\":\"%I64d\",\"symbol\":\"%s\",\"company\":\"%s\",\"currency\":\"%s\",\"balance\":%.2f,\"equity\":%.2f}\n",
      AccountInfoInteger(ACCOUNT_LOGIN), _Symbol, AccountInfoString(ACCOUNT_COMPANY), AccountInfoString(ACCOUNT_CURRENCY),
      m_account.Balance(), m_account.Equity()
   );
   SendString(regJson);

   // Reconcile and catch up historical bars on connect/reconnect
   SyncHistoricalBars();
   return true;
}

//+------------------------------------------------------------------+
//| Synchronize Historical M1 Bars to Python Brain on Reconnect      |
//+------------------------------------------------------------------+
void SyncHistoricalBars()
{
   if(!m_connected || m_socket == INVALID_HANDLE)
      return;

   MqlRates rates[];
   ArraySetAsSeries(rates, false); // rates[0] is oldest, rates[copied-1] is newest
   int copied = CopyRates(_Symbol, PERIOD_M1, 1, InpSyncBars, rates);
   if(copied <= 0)
   {
      PrintFormat("[LLM Bridge] Historical sync skipped. CopyRates returned %d. Error: %d", copied, GetLastError());
      return;
   }

   PrintFormat("[LLM Bridge] Synchronizing %d historical M1 bars with Python Brain...", copied);

   int chunkSize = 60; // 60 bars per batch (~4-5 KB per chunk)
   int totalBatches = (copied + chunkSize - 1) / chunkSize;

   for(int b = 0; b < totalBatches; b++)
   {
      int startIdx = b * chunkSize;
      int endIdx = MathMin(startIdx + chunkSize, copied);

      string barsJson = "";
      for(int i = startIdx; i < endIdx; i++)
      {
         long barTimeMs = (long)rates[i].time * 1000;
         double spread = (rates[i].spread > 0) ? (rates[i].spread * _Point) : 0.20;
         long vol = (rates[i].tick_volume > 0) ? rates[i].tick_volume : 1;

         string item = StringFormat(
            "{\"time\":%I64d,\"open\":%.2f,\"high\":%.2f,\"low\":%.2f,\"close\":%.2f,\"volume\":%I64d,\"spread\":%.2f}",
            barTimeMs, rates[i].open, rates[i].high, rates[i].low, rates[i].close, vol, spread
         );

         if(barsJson != "")
            barsJson += ",";
         barsJson += item;
      }

      string payload = StringFormat(
         "{\"type\":\"BAR_SYNC\",\"symbol\":\"%s\",\"batch\":%d,\"total\":%d,\"bars\":[%s]}\n",
         _Symbol, b + 1, totalBatches, barsJson
      );

      if(!SendString(payload))
      {
         PrintFormat("[LLM Bridge] Failed to send BAR_SYNC batch %d/%d", b + 1, totalBatches);
         break;
      }
   }

   PrintFormat("[LLM Bridge] Historical sync complete! Sent %d bars across %d batches.", copied, totalBatches);
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
int m_consecutive_send_fails = 0;

bool SendString(string data)
{
   if(!m_connected || m_socket == INVALID_HANDLE)
      return false;

   uchar buffer[];
   int len = StringToCharArray(data, buffer, 0, -1, CP_UTF8) - 1; // Drop null terminator, explicit UTF-8
   if(len <= 0)
      return false;

   ResetLastError();
   int sent = SocketSend(m_socket, buffer, len);
   if(sent == len)
   {
      m_consecutive_send_fails = 0;
      return true;
   }

   int err = GetLastError();
   m_consecutive_send_fails++;

   // If temporary failure on high-frequency tick, do not tear down socket
   if(m_consecutive_send_fails < 5)
   {
      return false; // Skip this individual tick cleanly
   }

   PrintFormat("[LLM Bridge] SocketSend connection lost after %d failures. Sent %d of %d bytes. Error: %d", m_consecutive_send_fails, sent, len, err);
   m_consecutive_send_fails = 0;
   DisconnectServer();
   return false;
}

//+------------------------------------------------------------------+
//| Read Incoming Data from Python Brain                             |
//+------------------------------------------------------------------+
void PollIncomingCommands()
{
   if(!m_connected || m_socket == INVALID_HANDLE)
      return;

   // Only read when bytes are ready to avoid socket timeout error 5273
   uint readable = SocketIsReadable(m_socket);
   if(readable > 0)
   {
      uchar buffer[];
      ArrayResize(buffer, readable + 32);
      ResetLastError();
      int received = SocketRead(m_socket, buffer, readable, InpTimeoutMs);
      if(received > 0)
      {
         string chunk = CharArrayToString(buffer, 0, received, CP_UTF8);
         m_incoming_buffer += chunk;
      }
   }

   // Process complete newline-delimited JSON commands from stream buffer
   while(StringFind(m_incoming_buffer, "\n") >= 0)
   {
      int newlinePos = StringFind(m_incoming_buffer, "\n");
      string line = StringSubstr(m_incoming_buffer, 0, newlinePos);
      m_incoming_buffer = StringSubstr(m_incoming_buffer, newlinePos + 1);
      
      StringTrimLeft(line);
      StringTrimRight(line);
      if(line != "")
      {
         PrintFormat("[LLM Bridge] Received command from Python: %s", line);
         ProcessCommand(line);
      }
   }
}

//+------------------------------------------------------------------+
//| Robust JSON Value Extractor Helper (Handles spaces & types)       |
//+------------------------------------------------------------------+
string ExtractJsonString(string json, string key)
{
   string search = "\"" + key + "\"";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos += StringLen(search);
   
   // Skip spaces and locate ':'
   while(pos < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, pos);
      if(ch == ':') { pos++; break; }
      pos++;
   }
   
   // Skip whitespace until value starts
   while(pos < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, pos);
      if(ch != ' ' && ch != '\t' && ch != '\r' && ch != '\n') break;
      pos++;
   }

   if(pos >= StringLen(json)) return "";

   // Check if string is enclosed in quotes
   if(StringGetCharacter(json, pos) == '\"')
   {
      pos++; // skip opening quote
      int end = StringFind(json, "\"", pos);
      if(end < 0) return "";
      return StringSubstr(json, pos, end - pos);
   }

   // Non-quoted value (number, boolean, or identifier)
   int end = pos;
   while(end < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, end);
      if(ch == ',' || ch == '}' || ch == '\n' || ch == '\r') break;
      end++;
   }
   string val = StringSubstr(json, pos, end - pos);
   StringTrimLeft(val);
   StringTrimRight(val);
   return val;
}

double ExtractJsonDouble(string json, string key)
{
   string val = ExtractJsonString(json, key);
   if(val == "") return 0.0;
   return StringToDouble(val);
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

   if(action == "SYNC_BARS")
   {
      SyncHistoricalBars();
      return;
   }

   if(action == "ORDER")
   {
      string symbol    = ExtractJsonString(cmdJson, "symbol");
      string side      = ExtractJsonString(cmdJson, "side");
      double lots      = ExtractJsonDouble(cmdJson, "lots");
      double price     = ExtractJsonDouble(cmdJson, "price");
      double sl        = ExtractJsonDouble(cmdJson, "sl");
      double tp        = ExtractJsonDouble(cmdJson, "tp");
      string comment   = ExtractJsonString(cmdJson, "comment");
      long   magic     = (long)ExtractJsonDouble(cmdJson, "magic");

      if(symbol == "") symbol = _Symbol;
      if(comment == "") comment = "LLM_AI_Trade";
      if(magic <= 0) magic = (long)InpMagicNumber;

      // 1. Check Terminal Algo Trading Master Switch
      if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      {
         string receipt = StringFormat(
            "{\"type\":\"ORDER_RECEIPT\",\"symbol\":\"%s\",\"side\":\"%s\",\"lots\":%.2f,\"success\":false,\"ticket\":0,\"retcode\":10027,\"retcode_desc\":\"Algo Trading is DISABLED in MT5 toolbar! Click Algo Trading button.\",\"price\":0.0,\"magic\":%I64u}\n",
            symbol, side, lots, (ulong)magic
         );
         SendString(receipt);
         Print("[LLM Bridge] ❌ ORDER REJECTED: Algo Trading button in MT5 toolbar is turned OFF! (Retcode: 10027)");
         return;
      }

      // 2. Check EA Automated Trading Permission
      if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
      {
         string receipt = StringFormat(
            "{\"type\":\"ORDER_RECEIPT\",\"symbol\":\"%s\",\"side\":\"%s\",\"lots\":%.2f,\"success\":false,\"ticket\":0,\"retcode\":10026,\"retcode_desc\":\"EA Automated Trading not allowed! Check 'Allow Algo Trading' in EA properties.\",\"price\":0.0,\"magic\":%I64u}\n",
            symbol, side, lots, (ulong)magic
         );
         SendString(receipt);
         Print("[LLM Bridge] ❌ ORDER REJECTED: 'Allow Algo Trading' is not checked in EA properties! (Retcode: 10026)");
         return;
      }

      m_trade.SetExpertMagicNumber((ulong)magic);

      // 3. Set proper filling mode for this symbol
      uint symFilling = (uint)SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
      if((symFilling & SYMBOL_FILLING_FOK) != 0)
         m_trade.SetTypeFilling(ORDER_FILLING_FOK);
      else if((symFilling & SYMBOL_FILLING_IOC) != 0)
         m_trade.SetTypeFilling(ORDER_FILLING_IOC);
      else
         m_trade.SetTypeFilling(ORDER_FILLING_RETURN);

      bool success = false;
      if(side == "BUY")
      {
         // For market execution, 0.0 allows CTrade to fetch current ask automatically
         double execPrice = (price > 0.0) ? price : 0.0;
         success = m_trade.Buy(lots, symbol, execPrice, sl, tp, comment);
      }
      else if(side == "SELL")
      {
         // For market execution, 0.0 allows CTrade to fetch current bid automatically
         double execPrice = (price > 0.0) ? price : 0.0;
         success = m_trade.Sell(lots, symbol, execPrice, sl, tp, comment);
      }
      else if(side == "BUY_LIMIT")
      {
         double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
         double execPrice = (price > 0.0) ? price : (ask - 2.0);
         success = m_trade.BuyLimit(lots, execPrice, symbol, sl, tp, ORDER_TIME_GTC, 0, comment);
      }
      else if(side == "SELL_LIMIT")
      {
         double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
         double execPrice = (price > 0.0) ? price : (bid + 2.0);
         success = m_trade.SellLimit(lots, execPrice, symbol, sl, tp, ORDER_TIME_GTC, 0, comment);
      }

      // Send execution receipt back to Python
      string receipt = StringFormat(
         "{\"type\":\"ORDER_RECEIPT\",\"symbol\":\"%s\",\"side\":\"%s\",\"lots\":%.2f,\"success\":%s,\"ticket\":%I64u,\"retcode\":%u,\"retcode_desc\":\"%s\",\"deal\":%I64u,\"price\":%.2f,\"magic\":%I64u}\n",
         symbol, side, lots, success ? "true" : "false",
         m_trade.ResultOrder(), m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription(), m_trade.ResultDeal(), m_trade.ResultPrice(), (ulong)magic
      );
      SendString(receipt);
      PrintFormat("[LLM Bridge] Order %s %s %.2f (Magic: %I64u) -> Result: %s (Ticket: %I64u, Retcode: %u - %s, Deal: %I64u, Price: %.2f)",
                  side, symbol, lots, (ulong)magic, success ? "OK" : "FAILED", m_trade.ResultOrder(), m_trade.ResultRetcode(), m_trade.ResultRetcodeDescription(), m_trade.ResultDeal(), m_trade.ResultPrice());
   }
   else if(action == "CLOSE_ALL")
   {
      string symbol = ExtractJsonString(cmdJson, "symbol");
      long   magic  = (long)ExtractJsonDouble(cmdJson, "magic");
      int closedPos = 0;
      int deletedOrders = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         if(m_position.SelectByIndex(i))
         {
            bool matchMagic = (magic <= 0) || (m_position.Magic() == (ulong)magic);
            if(matchMagic && (symbol == "" || m_position.Symbol() == symbol))
            {
               if(m_trade.PositionClose(m_position.Ticket()))
                  closedPos++;
            }
         }
      }
      for(int i = OrdersTotal() - 1; i >= 0; i--)
      {
         ulong ticket = OrderGetTicket(i);
         if(ticket > 0)
         {
            long ordMagic = OrderGetInteger(ORDER_MAGIC);
            string ordSym = OrderGetString(ORDER_SYMBOL);
            bool matchMagic = (magic <= 0) || (ordMagic == magic);
            if(matchMagic && (symbol == "" || ordSym == symbol))
            {
               if(m_trade.OrderDelete(ticket))
                  deletedOrders++;
            }
         }
      }
      string receipt = StringFormat(
         "{\"type\":\"ORDER_RECEIPT\",\"action\":\"CLOSE_ALL\",\"symbol\":\"%s\",\"closed_positions\":%d,\"deleted_orders\":%d,\"magic\":%I64u,\"success\":true}\n",
         symbol, closedPos, deletedOrders, (ulong)magic
      );
      SendString(receipt);
      PrintFormat("[LLM Bridge] Close All -> Closed %d positions, deleted %d pending orders", closedPos, deletedOrders);
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

   // Count open positions for our dual engines (1001 Scalp / 2001 Intraday)
   int openCount = 0;
   double totalUnrealized = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(m_position.SelectByIndex(i))
      {
         ulong posMagic = m_position.Magic();
         if((posMagic == 1001 || posMagic == 2001 || posMagic == InpMagicNumber) && m_position.Symbol() == _Symbol)
         {
            openCount++;
            totalUnrealized += m_position.Profit();
         }
      }
   }

   // Format JSON tick payload with Account ID for multi-account governance
   string tickJson = StringFormat(
      "{\"type\":\"TICK\",\"account_id\":\"%I64d\",\"symbol\":\"%s\",\"bid\":%.2f,\"ask\":%.2f,\"spread\":%.2f,\"time\":%I64d,\"equity\":%.2f,\"balance\":%.2f,\"open_positions\":%d,\"unrealized\":%.2f}\n",
      AccountInfoInteger(ACCOUNT_LOGIN), _Symbol, bid, ask, spread, timeMs,
      m_account.Equity(), m_account.Balance(), openCount, totalUnrealized
   );

   SendString(tickJson);

   // Check if Python sent back commands
   PollIncomingCommands();
}

//+------------------------------------------------------------------+
//| Timer function (Heartbeat, Reconnect & Sleep-Wake Auto-Sync)     |
//+------------------------------------------------------------------+
void OnTimer()
{
   ulong now_ms = GetTickCount64();

   // 1. Detect Laptop Sleep / Resume or Timer Stalls (> 4 seconds elapsed on a 1-second timer)
   if(m_last_timer_ms > 0 && (now_ms - m_last_timer_ms > 4000))
   {
      PrintFormat("[LLM Bridge] Laptop Sleep/Wake detected (Elapsed: %I64d ms). Refreshing connection and historical bars...", now_ms - m_last_timer_ms);
      DisconnectServer();
      ConnectToServer();
      m_last_timer_ms = now_ms;
      return;
   }
   m_last_timer_ms = now_ms;

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
      PollIncomingCommands();
   }
}
//+------------------------------------------------------------------+
