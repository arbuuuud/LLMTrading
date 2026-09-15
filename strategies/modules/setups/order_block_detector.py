from typing import Dict, Any, List, Optional
import polars as pl

class OrderBlockDetector:
    def __init__(self, ob_lookback_candles: int = 4):
        """
        Initializes the OrderBlockDetector.
        :param ob_lookback_candles: Number of candles to look back to identify the 'last opposing candle'.
                                   A smaller number (e.g., 1-4) is common for the actual OB candle itself.
        """
        self.ob_lookback_candles = ob_lookback_candles

    def find_order_blocks(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Detects Order Blocks (OB) in a given DataFrame of OHLC bars.
        This version uses a controlled Python loop over an enriched list of dictionaries
        to detect patterns, as complex sequential candle patterns are not yet fully
        vectorized in Polars without more advanced UDFs (map_every, rolling_map).

        Definition:
        - Bullish OB: A bearish candle (close < open) that precedes a strong bullish impulsive move.
                      A 'strong bullish impulsive move' is defined by the current candle's high
                      breaking above the maximum high of the `ob_lookback_candles` range preceding it.
                      The OB price is the low of the *last* bearish candle within that lookback.

        - Bearish OB: A bullish candle (close > open) that precedes a strong bearish impulsive move.
                      A 'strong bearish impulsive move' is defined by the current candle's low
                      breaking below the minimum low of the `ob_lookback_candles` range preceding it.
                      The OB price is the high of the *last* bullish candle within that lookback.
        """
        # Add is_bearish and is_bullish flags for easier condition checking
        df_temp = df.with_columns([
            (pl.col("close") < pl.col("open")).alias("is_bearish"),
            (pl.col("close") > pl.col("open")).alias("is_bullish"),
        ])

        # Convert to a list of dictionaries for easier row-wise access and in-place updates
        rows = df_temp.to_dicts()
        
        # Explicitly initialize OB columns in the list of dicts.
        for row in rows:
            row["bullish_ob_price"] = None
            row["bearish_ob_price"] = None
            row["bullish_ob_candle_idx"] = None
            row["bearish_ob_candle_idx"] = None
        
        # Iterate over rows to detect OBs
        # Start the loop after the lookback period is available
        for i in range(self.ob_lookback_candles, len(rows)):
            current_candle = rows[i]

            # --- Bullish Order Block Detection ---
            # Impulse up: Current candle's high breaks the highest high of the lookback period (excluding current)
            prev_highs_in_lookback = [rows[k]["high"] for k in range(i - self.ob_lookback_candles, i)]
            if current_candle["high"] > max(prev_highs_in_lookback): # Impulse up detected
                # Find the last bearish candle within the lookback period (prior to current impulse)
                for j in range(i - 1, i - self.ob_lookback_candles - 1, -1): # Iterate backwards
                    potential_ob_candle = rows[j]
                    if potential_ob_candle["is_bearish"]:
                        rows[i]["bullish_ob_price"] = potential_ob_candle["low"]
                        rows[i]["bullish_ob_candle_idx"] = j
                        break # Found the last suitable bearish OB candle, break and check next current_candle

            # --- Bearish Order Block Detection ---
            # Impulse down: Current candle's low breaks the lowest low of the lookback period (excluding current)
            prev_lows_in_lookback = [rows[k]["low"] for k in range(i - self.ob_lookback_candles, i)]
            if current_candle["low"] < min(prev_lows_in_lookback): # Impulse down detected
                # Find the last bullish candle within the lookback period (prior to current impulse)
                for j in range(i - 1, i - self.ob_lookback_candles - 1, -1): # Iterate backwards
                    potential_ob_candle = rows[j]
                    if potential_ob_candle["is_bullish"]:
                        rows[i]["bearish_ob_price"] = potential_ob_candle["high"]
                        rows[i]["bearish_ob_candle_idx"] = j
                        break # Found the last suitable bullish OB candle, break and check next current_candle
        
        # Define schema explicitly for the new columns to avoid inference issues with None values
        # Copy the schema from df_temp (which includes is_bearish and is_bullish) and add new columns
        schema = df_temp.schema.copy() 
        schema["bullish_ob_price"] = pl.Float64
        schema["bearish_ob_price"] = pl.Float64
        schema["bullish_ob_candle_idx"] = pl.Int64
        schema["bearish_ob_candle_idx"] = pl.Int64

        return pl.DataFrame(rows, schema=schema)


if __name__ == "__main__":
    print("Running OrderBlockDetector example...")

    # Create a dummy DataFrame with clear OB scenarios for testing
    # ob_lookback_candles = 4
    data = {
        "timestamp": pl.datetime_range(pl.datetime(2023, 1, 1), pl.datetime(2023, 1, 1, 0, 15), "1m", eager=True),
        "open": [
            10.0, 10.2, 10.1, 10.3, # Candles 0-3
            10.2, # Candle 4 (Bearish): potential Bullish OB
            11.0, 12.0, 13.0, # Candles 5-7: Strong bullish impulse after candle 4
            12.5, # Candle 8 (Bullish): potential Bearish OB
            11.0, 10.0, 9.0, # Candles 9-11: Strong bearish impulse after candle 8
            9.5, 9.2, 9.0, 8.8 # Candles 12-15
        ],
        "high": [
            10.5, 10.5, 10.4, 10.6,
            10.3, # High of candle 4
            11.5, 12.5, 13.5,
            13.0, # High of candle 8
            11.5, 10.5, 9.5,
            10.0, 9.5, 9.2, 9.0
        ],
        "low": [
            9.8, 10.0, 9.9, 10.1,
            9.7,  # Low of candle 4
            10.0, 11.0, 12.0,
            12.0, # Low of candle 8
            9.0, 8.0, 7.0,
            8.5, 8.2, 8.0, 7.8
        ],
        "close": [
            10.2, 10.1, 10.3, 10.2,
            9.8,  # Close < Open (bearish) - Candle 4 (OB candle low=9.7)
            11.0, 12.0, 13.0, # Bullish impulse: High at candle 7 (13.5) is > High of candle 4 (10.3)
            12.0, # Close > Open (bullish) - Candle 8 (OB candle high=13.0)
            10.0, 9.0, 8.0, # Bearish impulse: Low at candle 11 (7.0) is < Low of candle 8 (12.0)
            9.0, 8.5, 8.2, 8.0
        ],
    }
    df = pl.DataFrame(data, schema={
        "timestamp": pl.Datetime,
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
    })

    detector = OrderBlockDetector(ob_lookback_candles=4) # Smaller lookback for this example
    df_with_ob = detector.find_order_blocks(df)
    print(df_with_ob)
    print("OrderBlockDetector example finished.")
