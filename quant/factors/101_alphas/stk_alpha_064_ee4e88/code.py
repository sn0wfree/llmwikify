import math

def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Window sizes (ceiling of non-integer values)
    w_sum1 = math.ceil(12.7054)   # 13
    w_corr = math.ceil(16.6208)   # 17
    w_delta = math.ceil(3.69741)  # 4
    
    # adv120: 120-day rolling mean of volume
    df = df.with_columns(
        rolling_mean(pl.col('volume'), window=120).alias('_adv120')
    )
    
    # Part A: weighted price = open * 0.178404 + low * (1 - 0.178404)
    a_price = (pl.col('open') * 0.178404) + (pl.col('low') * (1 - 0.178404))
    
    # Materialize rolling sums first
    df = df.with_columns(
        rolling_sum(a_price, window=w_sum1).alias('_a_price_sum'),
        rolling_sum(pl.col('_adv120'), window=w_sum1).alias('_a_adv_sum')
    )
    
    # Rolling correlation between price sum and adv sum
    df = df.with_columns(
        correlation(pl.col('_a_price_sum'), pl.col('_a_adv_sum'), window=w_corr).alias('_a_corr')
    )
    
    # Part B: weighted price = ((high+low)/2) * 0.178404 + vwap * (1 - 0.178404)
    b_price = ((pl.col('high') + pl.col('low')) / 2) * 0.178404 + pl.col('vwap') * (1 - 0.178404)
    
    # Delta with periods=4
    df = df.with_columns(
        delta(b_price, periods=w_delta).alias('_b_delta')
    )
    
    # Cross-sectional ranks
    a_rank = rank(pl.col('_a_corr')).over('date')
    b_rank = rank(pl.col('_b_delta')).over('date')
    
    # Final: -1 if rank(corr) < rank(delta), else 0
    factor = pl.when(a_rank < b_rank).then(-1).otherwise(0)
    
    return df.select(factor).to_series()