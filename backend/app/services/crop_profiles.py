"""Generalised agronomic parameters (FAO-56 style Kc, published heat-stress thresholds).
These are rules of thumb, not local recommendations — the UI/agent tells farmers to confirm with their KVK."""
CROPS = {
    "rice":      dict(label="Rice (paddy)",  mandi="Paddy(Dhan)(Common)", heat=35, kc=1.15, sow=(20, 35), waterlog=150),
    "wheat":     dict(label="Wheat",         mandi="Wheat",               heat=32, kc=1.10, sow=(10, 25), waterlog=60),
    "maize":     dict(label="Maize",         mandi="Maize",               heat=35, kc=1.15, sow=(15, 35), waterlog=70),
    "cotton":    dict(label="Cotton",        mandi="Cotton",              heat=38, kc=1.10, sow=(18, 38), waterlog=80),
    "soybean":   dict(label="Soybean",       mandi="Soyabean",            heat=35, kc=1.10, sow=(15, 35), waterlog=70),
    "groundnut": dict(label="Groundnut",     mandi="Groundnut",           heat=36, kc=1.05, sow=(18, 35), waterlog=60),
    "mustard":   dict(label="Mustard",       mandi="Mustard",             heat=30, kc=1.05, sow=(10, 28), waterlog=50),
    "potato":    dict(label="Potato",        mandi="Potato",              heat=28, kc=1.10, sow=(10, 22), waterlog=50),
    "tomato":    dict(label="Tomato",        mandi="Tomato",              heat=33, kc=1.10, sow=(15, 32), waterlog=60),
    "sugarcane": dict(label="Sugarcane",     mandi="Sugarcane",           heat=38, kc=1.20, sow=(20, 38), waterlog=120),
    "chickpea":  dict(label="Chickpea",      mandi="Bengal Gram(Gram)(Whole)", heat=32, kc=1.00, sow=(15, 30), waterlog=50),
}
