from plot import plot_equity

# ... dopo aver stampato result.summary():

    print("=" * 45)
    for k, v in result.summary().items():
        print(f"{k:.<25} {v}")
    print("=" * 45)

    # Genera il grafico
    plot_equity(result)