def compute_factor(df: pl.DataFrame) -> pl.Series:
    df = df.sort(['code', 'date'])

    # adv81: 81-day average volume
    adv81 = ts_mean(pl.col('volume'), window=81)

    # Part 1: rank(decay_linear(delta(vwap, 1.24383), 11.8259))
    delta_vwap = delta(pl.col('vwap'), periods=1)
    decay_vwap = decay_linear(delta_vwap, window=12)
    rank_decay = rank(decay_vwap).over('date')

    # Part 2: Ts_Rank(decay_linear(Ts_Rank(correlation(IndNeutralize(low, sector), adv81, 8.14941), 19.569), 17.1543), 19.383)
    # No sector data available; using neutralize as substitute for IndNeutralize
    neutralized_low = neutralize(pl.col('low')).over('date')
    corr = rolling_corr(neutralized_low, adv81, window=8)
    ts_rank_corr = ts_rank(corr, window=20)
    decay_corr = decay_linear(ts_rank_corr, window=17)
    final_ts_rank = ts_rank(decay_corr, window=19)

    # Element-wise max of the two parts
    max_val = pl.max_horizontal(rank_decay, final_ts_rank)

    # Multiply by -1
    factor = max_val * -1

    return df.select(factor).to_series()