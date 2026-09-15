//+------------------------------------------------------------------+
//|                                     LLM_Scalp_VisualTester.mq5   |
//|                         Institutional AI Visual Strategy Tester  |
//|                                  Copyright 2026, LLMTrading Core |
//+------------------------------------------------------------------+
#property copyright   "LLMTrading Core"
#property link        "https://github.com/alami/LLMTrading"
#property version     "1.00"
#property description "Native MQL5 Visual Strategy Tester running the Institutional Scalper"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--- INPUT PARAMETERS
input group "Strategy Settings"
input double   InpLots           = 0.10;         // Fixed Lot Size (or test sizing)
input double   InpRiskReward     = 2.0;          // Risk-to-Reward Ratio (1:2.0)
input double   InpSLBuffer       = 0.35;         // Stop Loss Buffer ($)
input int      InpMaxBarsHold    = 25;           // Max M1 Bars in Trade (Time Exit)
input int      InpEMAPeriod      = 50;           // Trend EMA Period (M15)

input group "Session Filter Settings"
input bool     InpUseSessionFilter = true;       // Enable Session Prime Hours
input int      InpLondonStartHour= 7;            // London Session Start Hour (Broker Time)
input int      InpLondonEndHour  = 11;           // London Session End Hour
input int      InpNYStartHour    = 13;           // NY Session Start Hour
input int      InpNYEndHour      = 17;           // NY Session End Hour

input group "Visual & Safety Settings"
input bool     InpDrawZones      = true;         // Draw Supply/Demand Rectangles
input double   InpMaxSpread      = 0.25;         // Max Spread Allowed ($)
input ulong    InpMagicNumber    = 999002;       // Magic Number

//--- STRUCTS
struct SDZone {
   bool   isDemand;     // True = Demand (RBR), False = Supply (DBD)
   double high;
   double low;
   datetime time;
   string name;
};

//--- GLOBALS
CTrade         m_trade;
CPositionInfo  m_position;
CAccountInfo   m_account;
int            m_handleEMA;
SDZone         m_zones[];
datetime       m_last_bar_time = 0;
int            m_bars_in_trade = 0;
int            m_zone_counter = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(20);
   m_trade.SetTypeFilling(ORDER_FILLING_IOC);

   m_handleEMA = iMA(_Symbol, PERIOD_M15, InpEMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
   if(m_handleEMA == INVALID_HANDLE)
   {
      Print("[Visual Tester] Failed to initialize M15 EMA indicator.");
      return(INIT_FAILED);
   }

   ArrayResize(m_zones, 0);
   PrintFormat("[Visual Tester] Initialized for %s on M1. R:R 1:%.1f | Max Hold: %d bars.",
               _Symbol, InpRiskReward, InpMaxBarsHold);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(m_handleEMA != INVALID_HANDLE)
      IndicatorRelease(m_handleEMA);

   // Clear visual chart objects
   ObjectsDeleteAll(0, "SD_Zone_");
}

//+------------------------------------------------------------------+
//| Check if Time is in Prime Trading Hours                          |
//+------------------------------------------------------------------+
bool IsInTradeSession(datetime dt)
{
   if(!InpUseSessionFilter)
      return true;

   MqlDateTime mdt;
   TimeToStruct(dt, mdt);

   bool is_london = (mdt.hour >= InpLondonStartHour && mdt.hour < InpLondonEndHour);
   bool is_ny     = (mdt.hour >= InpNYStartHour && mdt.hour < InpNYEndHour);
   return (is_london || is_ny);
}

//+------------------------------------------------------------------+
//| Draw Visual Supply/Demand Zone Box on Chart                      |
//+------------------------------------------------------------------+
void DrawZoneOnChart(const SDZone &zone)
{
   if(!InpDrawZones) return;

   string name = zone.name;
   ObjectDelete(0, name);

   datetime time2 = zone.time + 3600 * 4; // Extend box 4 hours forward
   ObjectCreate(0, name, OBJ_RECTANGLE, 0, zone.time, zone.high, time2, zone.low);
   ObjectSetInteger(0, name, OBJPROP_COLOR, zone.isDemand ? clrPaleGreen : clrLightPink);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
}

//+------------------------------------------------------------------+
//| Detect RBR (Demand) & DBD (Supply) Formations                    |
//+------------------------------------------------------------------+
void DetectSupplyDemand(const MqlRates &rates[], int total_bars)
{
   if(total_bars < 6) return;

   // Index 1 is the most recently completed candle
   // Index 2 is Base candle
   // Index 3 is Leg 1
   double leg2_body = MathAbs(rates[1].close - rates[1].open);
   double base_body = MathAbs(rates[2].close - rates[2].open);

   // Average volume
   long sum_vol = 0;
   for(int i = 1; i <= 15 && i < total_bars; i++)
      sum_vol += rates[i].tick_volume;
   long avg_vol = sum_vol / 15;

   // Check DBD (Supply Zone)
   if(rates[1].close < rates[1].open && rates[3].close < rates[3].open)
   {
      if(base_body > 0 && leg2_body > base_body * 1.3 && rates[1].tick_volume > avg_vol * 1.05)
      {
         SDZone z;
         z.isDemand = false;
         z.high = rates[2].high;
         z.low = rates[2].low;
         z.time = rates[2].time;
         z.name = StringFormat("SD_Zone_Supply_%d", ++m_zone_counter);

         int sz = ArraySize(m_zones);
         ArrayResize(m_zones, sz + 1);
         m_zones[sz] = z;
         DrawZoneOnChart(z);
      }
   }
   // Check RBR (Demand Zone)
   else if(rates[1].close > rates[1].open && rates[3].close > rates[3].open)
   {
      if(base_body > 0 && leg2_body > base_body * 1.3 && rates[1].tick_volume > avg_vol * 1.05)
      {
         SDZone z;
         z.isDemand = true;
         z.high = rates[2].high;
         z.low = rates[2].low;
         z.time = rates[2].time;
         z.name = StringFormat("SD_Zone_Demand_%d", ++m_zone_counter);

         int sz = ArraySize(m_zones);
         ArrayResize(m_zones, sz + 1);
         m_zones[sz] = z;
         DrawZoneOnChart(z);
      }
   }

   // Keep zones list bounded
   if(ArraySize(m_zones) > 25)
   {
      ObjectDelete(0, m_zones[0].name);
      ArrayRemove(m_zones, 0, 1);
   }
}

//+------------------------------------------------------------------+
//| Check if Price is inside active Demand Zone                      |
//+------------------------------------------------------------------+
bool IsInDemandZone(double price)
{
   for(int i = ArraySize(m_zones) - 1; i >= 0; i--)
   {
      if(m_zones[i].isDemand && price >= m_zones[i].low - 0.10 && price <= m_zones[i].high)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Check if Price is inside active Supply Zone                      |
//+------------------------------------------------------------------+
bool IsInSupplyZone(double price)
{
   for(int i = ArraySize(m_zones) - 1; i >= 0; i--)
   {
      if(!m_zones[i].isDemand && price <= m_zones[i].high + 0.10 && price >= m_zones[i].low)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Check Candlestick Rejection Patterns                             |
//+------------------------------------------------------------------+
bool IsBullishTrigger(const MqlRates &c, const MqlRates &p)
{
   double rng = c.high - c.low;
   if(rng < 0.10) return false;
   double body = MathAbs(c.close - c.open);
   double lower_wick = MathMin(c.open, c.close) - c.low;

   // 1. Hammer (Lower wick rejection)
   if((lower_wick / rng) >= 0.55 && (body / rng) <= 0.35)
      return true;

   // 2. Bullish Engulfing
   if(p.close < p.open && c.close > c.open && c.close >= p.open && c.open <= p.close)
      return true;

   return false;
}

bool IsBearishTrigger(const MqlRates &c, const MqlRates &p)
{
   double rng = c.high - c.low;
   if(rng < 0.10) return false;
   double body = MathAbs(c.close - c.open);
   double upper_wick = c.high - MathMax(c.open, c.close);

   // 1. Shooting star (Upper wick rejection)
   if((upper_wick / rng) >= 0.55 && (body / rng) <= 0.35)
      return true;

   // 2. Bearish Engulfing
   if(p.close > p.open && c.close < c.open && c.close <= p.open && c.open >= p.close)
      return true;

   return false;
}

//+------------------------------------------------------------------+
//| Count Open Positions by Magic Number                             |
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(m_position.SelectByIndex(i))
      {
         if(m_position.Magic() == InpMagicNumber && m_position.Symbol() == _Symbol)
            count++;
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Main Tick Handler                                                |
//+------------------------------------------------------------------+
void OnTick()
{
   datetime current_bar = iTime(_Symbol, PERIOD_M1, 0);
   if(current_bar == m_last_bar_time)
      return; // Only process on new M1 bar completion

   m_last_bar_time = current_bar;

   // Fetch recent M1 bars
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(_Symbol, PERIOD_M1, 0, 30, rates);
   if(copied < 25) return;

   // 1. Manage Active Position (Time Exit)
   if(CountOpenPositions() > 0)
   {
      m_bars_in_trade++;
      if(m_bars_in_trade >= InpMaxBarsHold)
      {
         for(int i = PositionsTotal() - 1; i >= 0; i--)
         {
            if(m_position.SelectByIndex(i))
            {
               if(m_position.Magic() == InpMagicNumber && m_position.Symbol() == _Symbol)
               {
                  m_trade.PositionClose(m_position.Ticket());
                  PrintFormat("[Visual Tester] TIME EXIT: Position closed after %d bars.", m_bars_in_trade);
               }
            }
         }
         m_bars_in_trade = 0;
      }
      return;
   }
   else
   {
      m_bars_in_trade = 0;
   }

   // 2. Spread Guard
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double spread = ask - bid;
   if(spread > InpMaxSpread)
      return;

   // 3. Session Filter
   if(!IsInTradeSession(rates[1].time))
      return;

   // 4. Update Supply & Demand Zones
   DetectSupplyDemand(rates, copied);

   // 5. Get M15 Trend Filter (EMA 50)
   double ema_val[1];
   if(CopyBuffer(m_handleEMA, 0, 1, 1, ema_val) <= 0)
      return;

   double close_price = rates[1].close;
   bool is_uptrend = (close_price >= ema_val[0]);
   bool is_downtrend = (close_price <= ema_val[0]);

   // 6. Evaluate Long Setup (Uptrend + In Demand + Bullish Trigger)
   if(is_uptrend && IsInDemandZone(close_price))
   {
      if(IsBullishTrigger(rates[1], rates[2]))
      {
         double sl = rates[1].low - InpSLBuffer;
         double risk_dist = ask - sl;
         if(risk_dist >= 0.40 && risk_dist <= 3.50)
         {
            double tp = ask + (risk_dist * InpRiskReward);
            sl = NormalizeDouble(sl, _Digits);
            tp = NormalizeDouble(tp, _Digits);
            if(m_trade.Buy(InpLots, _Symbol, ask, sl, tp, "AI_Scalp_Buy"))
            {
               PrintFormat("[Visual Tester] BUY OPENED @ %.2f | SL: %.2f | TP: %.2f (R:R 1:%.1f)",
                           ask, sl, tp, InpRiskReward);
            }
         }
      }
   }
   // 7. Evaluate Short Setup (Downtrend + In Supply + Bearish Trigger)
   else if(is_downtrend && IsInSupplyZone(close_price))
   {
      if(IsBearishTrigger(rates[1], rates[2]))
      {
         double sl = rates[1].high + InpSLBuffer;
         double risk_dist = sl - bid;
         if(risk_dist >= 0.40 && risk_dist <= 3.50)
         {
            double tp = bid - (risk_dist * InpRiskReward);
            sl = NormalizeDouble(sl, _Digits);
            tp = NormalizeDouble(tp, _Digits);
            if(m_trade.Sell(InpLots, _Symbol, bid, sl, tp, "AI_Scalp_Sell"))
            {
               PrintFormat("[Visual Tester] SELL OPENED @ %.2f | SL: %.2f | TP: %.2f (R:R 1:%.1f)",
                           bid, sl, tp, InpRiskReward);
            }
         }
      }
   }
}
//+------------------------------------------------------------------+
