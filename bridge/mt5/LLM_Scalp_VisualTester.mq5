//+------------------------------------------------------------------+
//|                                     LLM_Scalp_VisualTester.mq5   |
//|                         Institutional AI Visual Strategy Tester  |
//|                                  Copyright 2026, LLMTrading Core |
//+------------------------------------------------------------------+
#property copyright   "LLMTrading Core"
#property link        "https://github.com/alami/LLMTrading"
#property version     "2.00"
#property description "Upgraded High-Conviction Institutional Scalper for MT5 Strategy Tester"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>

//--- INPUT PARAMETERS
input group "=== Risk & Money Management ==="
input double   InpLots           = 0.10;         // Fixed Lot Size
input double   InpRiskReward     = 2.0;          // Risk-to-Reward Ratio (1:2.0)
input double   InpSLBuffer       = 0.35;         // Stop Loss Buffer beyond wick ($)
input int      InpMaxBarsHold    = 25;           // Max M1 Bars in Trade (Time-based Exit)

input group "=== Institutional Footprint (RBR / DBD) ==="
input double   InpMinImpulseRatio= 1.5;          // Min Impulse vs Base Body Ratio (1.5x)
input double   InpMinVolumeRatio = 1.2;          // Min Volume Expansion Ratio (1.2x)
input int      InpEMAPeriod      = 50;           // Trend Filter EMA (M15)
input bool     InpRequireEMASlope= true;         // Require EMA Slope Alignment

input group "=== Session Filter (Broker Server Time) ==="
input bool     InpUseSessionFilter = true;       // Enable Prime Hours Filter
input int      InpLondonStartHour= 10;           // London Open Start Hour (Broker Time, e.g. 10 for UTC+3)
input int      InpLondonEndHour  = 13;           // London Open End Hour
input int      InpNYStartHour    = 15;           // New York Open Start Hour (e.g. 15 for UTC+3)
input int      InpNYEndHour      = 18;           // New York Open End Hour

input group "=== Visual & Safety Settings ==="
input bool     InpDrawZones      = true;         // Draw Supply/Demand Rectangles on Chart
input double   InpMaxSpread      = 0.25;         // Max Allowed Spread ($0.25)
input ulong    InpMagicNumber    = 999002;       // Magic Number

//--- STRUCTS
struct SDZone {
   bool     isDemand;    // True = Demand (RBR), False = Supply (DBD)
   double   high;
   double   low;
   datetime time;
   string   name;
   bool     mitigated;
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
   PrintFormat("[Visual Tester v2.0] Initialized for %s. R:R 1:%.1f | London: %02d-%02d | NY: %02d-%02d",
               _Symbol, InpRiskReward, InpLondonStartHour, InpLondonEndHour, InpNYStartHour, InpNYEndHour);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(m_handleEMA != INVALID_HANDLE)
      IndicatorRelease(m_handleEMA);

   ObjectsDeleteAll(0, "SD_Zone_");
}

//+------------------------------------------------------------------+
//| Check Prime Session Hours                                        |
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
//| Draw Visual Supply/Demand Box                                    |
//+------------------------------------------------------------------+
void DrawZoneOnChart(const SDZone &zone)
{
   if(!InpDrawZones) return;

   string name = zone.name;
   ObjectDelete(0, name);

   datetime time2 = zone.time + 3600 * 3; // 3 hours forward
   ObjectCreate(0, name, OBJ_RECTANGLE, 0, zone.time, zone.high, time2, zone.low);
   ObjectSetInteger(0, name, OBJPROP_COLOR, zone.isDemand ? clrMediumSeaGreen : clrCrimson);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
}

//+------------------------------------------------------------------+
//| Detect High-Conviction Institutional Supply & Demand Zones       |
//+------------------------------------------------------------------+
void DetectSupplyDemand(const MqlRates &rates[], int total_bars)
{
   if(total_bars < 8) return;

   // Index 1: Displacement Candle (Leg 2)
   // Index 2: Base Consolidation Candle
   // Index 3: Origin Candle (Leg 1)
   double leg2_body = MathAbs(rates[1].close - rates[1].open);
   double leg2_range= rates[1].high - rates[1].low;
   double base_body = MathAbs(rates[2].close - rates[2].open);

   if(base_body <= 0.05 || leg2_range <= 0.20) return;

   // Volume baseline (15 bars average)
   long sum_vol = 0;
   for(int i = 1; i <= 15 && i < total_bars; i++)
      sum_vol += rates[i].tick_volume;
   long avg_vol = sum_vol / 15;

   // Check High-Conviction DBD (Drop - Base - Drop) Supply Zone
   if(rates[1].close < rates[1].open && rates[3].close < rates[3].open)
   {
      bool strong_body = (leg2_body / leg2_range) >= 0.60;
      bool impulse_ok  = leg2_body >= base_body * InpMinImpulseRatio;
      bool volume_ok   = rates[1].tick_volume >= avg_vol * InpMinVolumeRatio;

      if(strong_body && impulse_ok && volume_ok)
      {
         SDZone z;
         z.isDemand = false;
         z.high = rates[2].high;
         z.low = rates[2].low;
         z.time = rates[2].time;
         z.name = StringFormat("SD_Zone_Supply_%d", ++m_zone_counter);
         z.mitigated = false;

         int sz = ArraySize(m_zones);
         ArrayResize(m_zones, sz + 1);
         m_zones[sz] = z;
         DrawZoneOnChart(z);
      }
   }
   // Check High-Conviction RBR (Rally - Base - Rally) Demand Zone
   else if(rates[1].close > rates[1].open && rates[3].close > rates[3].open)
   {
      bool strong_body = (leg2_body / leg2_range) >= 0.60;
      bool impulse_ok  = leg2_body >= base_body * InpMinImpulseRatio;
      bool volume_ok   = rates[1].tick_volume >= avg_vol * InpMinVolumeRatio;

      if(strong_body && impulse_ok && volume_ok)
      {
         SDZone z;
         z.isDemand = true;
         z.high = rates[2].high;
         z.low = rates[2].low;
         z.time = rates[2].time;
         z.name = StringFormat("SD_Zone_Demand_%d", ++m_zone_counter);
         z.mitigated = false;

         int sz = ArraySize(m_zones);
         ArrayResize(m_zones, sz + 1);
         m_zones[sz] = z;
         DrawZoneOnChart(z);
      }
   }

   // Maintain active zones bounded
   if(ArraySize(m_zones) > 20)
   {
      ObjectDelete(0, m_zones[0].name);
      ArrayRemove(m_zones, 0, 1);
   }
}

//+------------------------------------------------------------------+
//| Check Unmitigated Demand Zone                                    |
//+------------------------------------------------------------------+
bool IsInDemandZone(double price, int &zone_idx)
{
   for(int i = ArraySize(m_zones) - 1; i >= 0; i--)
   {
      if(m_zones[i].isDemand && !m_zones[i].mitigated)
      {
         if(price >= m_zones[i].low - 0.15 && price <= m_zones[i].high + 0.05)
         {
            zone_idx = i;
            return true;
         }
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Check Unmitigated Supply Zone                                    |
//+------------------------------------------------------------------+
bool IsInSupplyZone(double price, int &zone_idx)
{
   for(int i = ArraySize(m_zones) - 1; i >= 0; i--)
   {
      if(!m_zones[i].isDemand && !m_zones[i].mitigated)
      {
         if(price <= m_zones[i].high + 0.15 && price >= m_zones[i].low - 0.05)
         {
            zone_idx = i;
            return true;
         }
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Candlestick Triggers                                             |
//+------------------------------------------------------------------+
bool IsBullishTrigger(const MqlRates &c, const MqlRates &p)
{
   double rng = c.high - c.low;
   if(rng < 0.15) return false;
   double body = MathAbs(c.close - c.open);
   double lower_wick = MathMin(c.open, c.close) - c.low;

   // Hammer (Strong Lower Wick Rejection)
   if((lower_wick / rng) >= 0.55 && (body / rng) <= 0.35)
      return true;

   // Bullish Engulfing
   if(p.close < p.open && c.close > c.open && c.close >= p.open && c.open <= p.close + 0.05)
      return true;

   return false;
}

bool IsBearishTrigger(const MqlRates &c, const MqlRates &p)
{
   double rng = c.high - c.low;
   if(rng < 0.15) return false;
   double body = MathAbs(c.close - c.open);
   double upper_wick = c.high - MathMax(c.open, c.close);

   // Shooting star (Strong Upper Wick Rejection)
   if((upper_wick / rng) >= 0.55 && (body / rng) <= 0.35)
      return true;

   // Bearish Engulfing
   if(p.close > p.open && c.close < c.open && c.close <= p.open && c.open >= p.close - 0.05)
      return true;

   return false;
}

//+------------------------------------------------------------------+
//| Count Open Positions                                             |
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
      return; // Bar close execution only

   m_last_bar_time = current_bar;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(_Symbol, PERIOD_M1, 0, 35, rates);
   if(copied < 30) return;

   // 1. Time-based Exit Guard (Max 25 bars in stagnant position)
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
                  PrintFormat("[Visual Tester] TIME EXIT: Closed trade after %d bars.", m_bars_in_trade);
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

   // 3. Session Hours Filter
   if(!IsInTradeSession(rates[1].time))
      return;

   // 4. Detect Supply & Demand Formations
   DetectSupplyDemand(rates, copied);

   // 5. M15 Trend Direction & Slope
   double ema_val[3];
   if(CopyBuffer(m_handleEMA, 0, 1, 3, ema_val) < 3)
      return;

   double close_price = rates[1].close;
   bool ema_bull_slope = (!InpRequireEMASlope || (ema_val[0] >= ema_val[2]));
   bool ema_bear_slope = (!InpRequireEMASlope || (ema_val[0] <= ema_val[2]));

   bool is_uptrend   = (close_price >= ema_val[0]) && ema_bull_slope;
   bool is_downtrend = (close_price <= ema_val[0]) && ema_bear_slope;

   int matched_zone = -1;

   // 6. Buy Setup: Uptrend + Inside Demand Zone + Bullish Candle Rejection
   if(is_uptrend && IsInDemandZone(close_price, matched_zone))
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
               m_zones[matched_zone].mitigated = true; // Mark zone as used
               PrintFormat("[Visual Tester] BUY @ %.2f | SL: %.2f | TP: %.2f (R:R 1:%.1f)",
                           ask, sl, tp, InpRiskReward);
            }
         }
      }
   }
   // 7. Sell Setup: Downtrend + Inside Supply Zone + Bearish Candle Rejection
   else if(is_downtrend && IsInSupplyZone(close_price, matched_zone))
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
               m_zones[matched_zone].mitigated = true; // Mark zone as used
               PrintFormat("[Visual Tester] SELL @ %.2f | SL: %.2f | TP: %.2f (R:R 1:%.1f)",
                           bid, sl, tp, InpRiskReward);
            }
         }
      }
   }
}
//+------------------------------------------------------------------+
