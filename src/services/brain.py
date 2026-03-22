def run_brain(trades):

    # 1. strategie váhy
    weights = StrategyWeights().get()

    # 2. performance
    perf = compute_performance(trades)

    # 3. evoluce
    evo = SelfEvolvingSystem().evolve(perf)

    # 4. meta eval
    meta = MetaEvaluator().evaluate(trades)
    fb = MetaEvaluator().feedback(meta)

    # 5. stabilizer
    stab = Stabilizer()
    stab.update(trades)
    stab_state = stab.get_state()

    # 6. složení configu
    config = {
        "weights": weights,
        "confidence_bias": fb.get("bias", 0),
        "confidence_scale": fb.get("scale", 1),
        "min_conf": stab_state["min_conf"],
        "risk_multiplier": evo.get("risk_multiplier", 1)
    }

    save_to_firebase(config)