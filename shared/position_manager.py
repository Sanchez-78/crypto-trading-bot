def compute_position_size(confidence, balance=1000, trust=1.0):
    base_risk = 0.01

    risk = base_risk * (0.5 + confidence) * trust

    size = balance * risk

    return round(size, 2)