//+------------------------------------------------------------------+
//|                                           ExportHistoryToCSV.mq5 |
//|                                  Copyright 2026, LLMTrading Auto |
//|             Institutional Data Exporter for AI Lifelong Learning |
//+------------------------------------------------------------------+
#property copyright "LLMTrading"
#property link      "https://github.com/LLMTrading"
#property version   "1.00"
#property script_show_inputs

enum ENUM_EXPORT_DATA
{
   EXPORT_TICKS_ALL = 0,    // Real Ticks (Bid, Ask, Spread, Flags)
   EXPORT_BARS_M1   = 1,    // 1-Minute Bars
   EXPORT_BARS_M5   = 2,    // 5-Minute Bars
   EXPORT_BARS_M15  = 3,    // 15-Minute Bars
   EXPORT_BARS_H1   = 4     // 1-Hour Bars
};

//--- Inputs
input string           InpSymbol      = "XAUUSD";          // Symbol (e.g. XAUUSD, XAGUSD, USDX)
input ENUM_EXPORT_DATA InpDataType    = EXPORT_TICKS_ALL;  // Data Type
input datetime         InpStartDate   = D'2024.01.01 00:00'; // Start Date (UTC)
input datetime         InpEndDate     = D'2026.12.31 23:59'; // End Date (UTC)

//+------------------------------------------------------------------+
//| Script program start function                                    |
//+------------------------------------------------------------------+
void OnStart()
{
   string symbol = InpSymbol;
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
         case EXPORT_BARS_M15: tf = PERIOD_M15; tf_str = "M15"; break;
         case EXPORT_BARS_H1:  tf = PERIOD_H1;  tf_str = "H1";  break;
      }
      ExportBars(symbol, tf, tf_str, InpStartDate, InpEndDate);
   }
}

//+------------------------------------------------------------------+
//| Export Ticks to CSV                                              |
//+------------------------------------------------------------------+
void ExportTicks(string symbol, datetime start_time, datetime end_time)
{
   ulong from_msc = (ulong)start_time * 1000;
   ulong to_msc   = (ulong)end_time * 1000;

   string filename = StringFormat("%s_ticks_%s_%s.csv",
                                  symbol,
                                  TimeToString(start_time, TIME_DATE),
                                  TimeToString(end_time, TIME_DATE));
   StringReplace(filename, ".", "");
   StringReplace(filename, ":", "");

   int handle = FileOpen(filename, FILE_WRITE | FILE_CSV | FILE_ANSI, '\t');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("[Exporter Error] Failed to open file %s for writing. Error=%d", filename, GetLastError());
      return;
   }

   // Write Header
   FileWriteString(handle, "<DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>\n");

   ulong current_from = from_msc;
   const uint CHUNK_SIZE = 250000;
   MqlTick ticks[];
   ulong total_exported = 0;

   while(!IsStopped() && current_from < to_msc)
   {
      int copied = CopyTicksRange(symbol, ticks, COPY_TICKS_ALL, current_from, to_msc);
      if(copied <= 0)
      {
         break;
      }

      for(int i = 0; i < copied; i++)
      {
         datetime dt = (datetime)(ticks[i].time_msc / 1000);
         uint ms = (uint)(ticks[i].time_msc % 1000);
         string date_str = TimeToString(dt, TIME_DATE);
         string time_str = StringFormat("%s.%03u", TimeToString(dt, TIME_SECONDS), ms);

         string line = StringFormat("%s\t%s\t%.3f\t%.3f\t%.3f\t%u\t%u\n",
                                    date_str,
                                    time_str,
                                    ticks[i].bid,
                                    ticks[i].ask,
                                    ticks[i].last,
                                    (uint)ticks[i].volume,
                                    (uint)ticks[i].flags);
         FileWriteString(handle, line);
      }

      total_exported += (ulong)copied;
      ulong last_msc = ticks[copied - 1].time_msc;
      if(last_msc <= current_from)
         current_from++;
      else
         current_from = last_msc + 1;

      PrintFormat("[Exporter] Exported %llu ticks so far (Last date: %s)...",
                  total_exported, TimeToString((datetime)(last_msc / 1000)));

      if(copied < (int)CHUNK_SIZE && current_from >= to_msc)
         break;
   }

   FileClose(handle);
   PrintFormat("[Exporter Success] Completed! Total %llu ticks exported to MQL5/Files/%s",
               total_exported, filename);
}

//+------------------------------------------------------------------+
//| Export Bars to CSV                                               |
//+------------------------------------------------------------------+
void ExportBars(string symbol, ENUM_TIMEFRAMES tf, string tf_str, datetime start_time, datetime end_time)
{
   MqlRates rates[];
   ArraySetAsSeries(rates, false);

   int copied = CopyRates(symbol, tf, start_time, end_time, rates);
   if(copied <= 0)
   {
      PrintFormat("[Exporter Error] Failed to copy rates for %s. Error=%d", symbol, GetLastError());
      return;
   }

   string filename = StringFormat("%s_%s_%s_%s.csv",
                                  symbol,
                                  tf_str,
                                  TimeToString(start_time, TIME_DATE),
                                  TimeToString(end_time, TIME_DATE));
   StringReplace(filename, ".", "");

   int handle = FileOpen(filename, FILE_WRITE | FILE_CSV | FILE_ANSI, '\t');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("[Exporter Error] Failed to open file %s. Error=%d", filename, GetLastError());
      return;
   }

   // Header
   FileWriteString(handle, "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICK_VOL>\t<VOL>\t<SPREAD>\n");

   for(int i = 0; i < copied; i++)
   {
      string date_str = TimeToString(rates[i].time, TIME_DATE);
      string time_str = TimeToString(rates[i].time, TIME_SECONDS);

      string line = StringFormat("%s\t%s\t%.3f\t%.3f\t%.3f\t%.3f\t%lld\t%lld\t%d\n",
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
   PrintFormat("[Exporter Success] Completed! %d %s bars exported to MQL5/Files/%s",
               copied, tf_str, filename);
}
