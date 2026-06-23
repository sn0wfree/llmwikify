def compute_factor(df: pl.DataFrame) -> pl.Series:
    # 1. Sort by (code, date) for per-code rolling
    df = df.sort(['code', 'date'])

    # 2. delta(close - 1, 5)
    close_minus_1 = pl.col('close') - 1
    d = delta(close_minus_1, periods=5)

    # 3. rank(delta(close - 1, 5))
    r1 = rank(d).over('date')

    # 4. -1 * rank(...)
    neg_r1 = -1 * r1

    # 5. rank(-1 * rank(...))
    r2 = rank(neg_r1).over('date')

    # 6. rank(rank(-1 * rank(delta(close - 1, 5))))
    r3 = rank(r2).over('date')

    # 7. ts_min(..., 2)  (use rolling_min since ts_min not in namespace)
    tmin = rolling_min(r3, window=2)

    # 8. sum(..., 1)  — rolling_sum window 1 is identity
    s = rolling_sum(tmin, window=1)

    # 9. log(...)
    logged = s.log()

    # 10. scale(log(...))
    sc = scale(logged).over('date')

    # 11. rank(scale(log(...)))
    r4 = rank(sc).over('date')

    # 12. rank(rank(scale(log(...))))
    r5 = rank(r4).over('date')

    # 13. product(..., 1) — window 1 product is identity
    p = r5

    # 14. min(..., 5)
    m = rolling_min(p, window=5)

    # 15. Second term: ts_rank(delay(-1 * returns, 6), 5)
    neg_ret = -1 * pl.col('returns')
    delayed = delay(neg_ret, periods=6)
    tr = ts_rank(delayed, window=5)

    # 16. Combine
    factor = m + tr

    return df.select(factor).to_series()