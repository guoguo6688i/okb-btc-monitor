# -*- coding: utf-8 -*-
import requests, datetime
for base in ["https://www.okx.com", "https://www.oyigwcn.biz"]:
    try:
        rows = []
        after = None
        for _ in range(6):
            p = {"instId": "OKB-BTC", "bar": "4H", "limit": "300"}
            if after:
                p["after"] = str(after)
            d = requests.get(base + "/api/v5/market/candles",
                             params=p, timeout=15).json()["data"]
            for r in d:
                rows.append((datetime.datetime.fromtimestamp(int(r[0]) / 1000),
                             float(r[2]), float(r[4])))
            after = int(d[-1][0])
            if len(d) < 300:
                break
        rows.sort()
        print("数据源成功:", base, "根数:", len(rows))
        print("=== 9-23以来 4H high >= 0.0016 ===")
        for t, h, c in rows:
            if t >= datetime.datetime(2026, 9, 23) and h >= 0.0016:
                print(t, "high", round(h, 6), "close", round(c, 6))
        break
    except Exception as e:
        print("失败:", base, e)
