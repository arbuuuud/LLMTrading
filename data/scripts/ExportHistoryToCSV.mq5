//+------------------------------------------------------------------+
//|                                           ExportHistoryToCSV.mq5 |
//|                                  Copyright 2026, LLMTrading Auto |
//|             Institutional Data Exporter for AI Lifelong Learning |
//+------------------------------------------------------------------+
#property copyright "LLMTrading"
#property link      "https://github.com/LLMTrading"
#property version     "1.10"
#property script_show_inputs

enum ENUM_EXPORT_DATA
{
   EXPORT_BARS_M1   = 0,    // 1-Minute Bars (Fast & Lightweight)
   EXPORT_BARS_M5   = 1,    // 5-Minute Bars
   EXPORT_BARS_H1   = 2,    // 1-Hour Bars
   EXPORT_TICKS_ALL = 3     // Real Ticks (Bid, Ask, Spread)
};

//--- Inputs
input string           InpSymbol      = "";                 // Symbol (Kosongkan = otomatis gunakan simbol chart)
input ENUM_EXPORT_DATA InpDataType    = EXPORT_BARS_M1;     // Data Type (Default: M1 Bars)
input datetime         InpStartDate   = D'2025.01.01 00:00'; // Start Date (UTC)
input datetime         InpEndDate     = D'2026.12.31 23:59'; // End Date (UTC)

void ExportBars(string symbol, ENUM_TIMEFRAMES tf, string tf_str, datetime start_time, datetime end_time);
void ExportTicks(string symbol, datetime start_time, datetime end_time);

//+------------------------------------------------------------------+
//| Script program start function                                    |
//+------------------------------------------------------------------+
void OnStart()
{
   string symbol = InpSymbol;
   StringTrimLeft(symbol);
   StringTrimRight(symbol);
   if(symbol == "" || symbol == "0")
      symbol = _Symbol;

   PrintFormat("[Exporter] Starting export for %s from %s to %s...",
               symbol, TimeToString(InpStartDate), TimeToString(InpEndDate));

   if(InpDataType == EXPORT_TICKS_ALL)
   {
      ExportTicks(symbol, InpStartDate, InpEndDate);
   }
   else
   {
      ENUM_TIMEFRAMES tf = PERIOD_M1;
      string tf_str = "M1";
      
      switch(InpDataType)
      {
         case EXPORT_BARS_M1:  tf = PERIOD_M1;  tf_str = "M1";  break;
         case EXPORT_BARS_M5:  tf = PERIOD_M5;  tf_str = "M5";  break;
         case EXPORT_BARS_H1:  tf = PERIOD_H1;  tf_str = "H1";  break;
      }
      ExportBars(symbol, tf, tf_str, InpStartDate, InpEndDate);
   }
}

//+------------------------------------------------------------------+
//| Export Bars to CSV with auto-retry and clean formatting          |
//+------------------------------------------------------------------+
void ExportBars(string symbol, ENUM_TIMEFRAMES tf, string tf_str, datetime start_time, datetime end_time)
{
   MqlRates rates[];
   ArraySetAsSeries(rates, false);

   // Retry up to 5 times while MT5 downloads history from broker server
   int copied = 0;
   for(int attempt = 1; attempt <= 5; attempt++)
   {
      copied = CopyRates(symbol, tf, start_time, end_time, rates);
      if(copied > 0)
         break;
      PrintFormat("[Exporter] Attempt %d: Downloading %s %s bars from broker...", attempt, symbol, tf_str);
      Sleep(1000);
   }

   if(copied <= 0)
   {
      PrintFormat("[Exporter Error] Failed to copy rates for %s (%s). Error=%d. Make sure the symbol chart is open.",
                  symbol, tf_str, GetLastError());
      return;
   }

   string d1 = TimeToString(start_time, TIME_DATE);
   StringReplace(d1, ".", "");
   string d2 = TimeToString(end_time, TIME_DATE);
   StringReplace(d2, ".", "");
   string filename = StringFormat("%s_%s_%s_%s.csv", symbol, tf_str, d1, d2);

   int handle = FileOpen(filename, FILE_WRITE | FILE_CSV | FILE_ANSI, '\t');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("[Exporter Error] Failed to open file %s. Error=%d", filename, GetLastError());
      return;
   }

   // Write Header
   FileWriteString(handle, "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n");

   for(int i = 0; i < copied; i++)
   {
      string date_str = TimeToString(rates[i].time, TIME_DATE);
      string time_str = TimeToString(rates[i].time, TIME_SECONDS);

      string line = StringFormat("%s\t%s\t%.5f\t%.5f\t%.5f\t%.5f\t%I64u\t%I64u\t%d\n",
                                 date_str,
                                 time_str,
                                 rates[i].open,
                                 rates[i].high,
                                 rates[i].low,
                                 rates[i].close,
                                 rates[i].tick_volume,
                                 rates[i].real_volume,
                                 rates[i].spread);
      FileWriteString(handle, line);
   }

   FileClose(handle);
   PrintFormat("[Exporter Success] COMPLETED! Exported %d bars to MQL5/Files/%s", copied, filename);
}

//+------------------------------------------------------------------+
//| Export Ticks to CSV                                              |
//+------------------------------------------------------------------+
void ExportTicks(string symbol, datetime start_time, datetime end_time)
{
   ulong from_msc = (ulong)start_time * 1000;
   ulong to_msc   = (ulong)end_time * 1000;

   string d1 = TimeToString(start_time, TIME_DATE);
   StringReplace(d1, ".", "");
   string d2 = TimeToString(end_time, TIME_DATE);
   StringReplace(d2, ".", "");
   string filename = StringFormat("%s_ticks_%s_%s.csv", symbol, d1, d2);

   int handle = FileOpen(filename, FILE_WRITE | FILE_CSV | FILE_ANSI, '\t');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("[Exporter Error] Failed to open file %s for writing. Error=%d", filename, GetLastError());
      return;
   }

   FileWriteString(handle, "<DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>\n");

   ulong current_from = from_msc;
   const uint CHUNK_SIZE = 250000;
   MqlTick ticks[];
   ulong total_exported = 0;

   while(!IsStopped() && current_from < to_msc)
   {
      int copied = CopyTicksRange(symbol, ticks, COPY_TICKS_ALL, current_from, to_msc);
      if(copied <= 0)
         break;

      for(int i = 0; i < copied; i++)
      {
         datetime dt = (datetime)(ticks[i].time_msc / 1000);
         uint ms = (uint)(ticks[i].time_msc % 1000);
         string date_str = TimeToString(dt, TIME_DATE);
         string time_str = StringFormat("%s.%03u", TimeToString(dt, TIME_SECONDS), ms);

         string line = StringFormat("%s\t%s\t%.5f\t%.5f\t%.5f\t%u\t%u\n",
                                    date_str,
                                    time_str,
                                    ticks[i].bid,
                                    ticks[i].ask,
                                    ticks[i].last,
                                    ticks[i].volume,
                                    ticks[i].flags);
         FileWriteString(handle, line);
      }

      total_exported += copied;
      current_from = ticks[copied - 1].time_msc + 1;
      if(copied < (int)CHUNK_SIZE)
         break;
   }

   FileClose(handle);
   PrintFormat("[Exporter Success] COMPLETED! Exported %llu ticks to MQL5/Files/%s", total_exported, filename);
}
//+------------------------------------------------------------------+
