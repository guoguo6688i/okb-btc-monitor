#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKB/BTC 信号查询工具（命令行版）
================================
运行后获取 OKX 实时数据，计算五因子打分，输出当前买入/持有/卖出信号。
用法：python check_signal.py
"""

import os
import requests
import numpy as np
from datetime import datetime, timedelta

# ============================================================
# 配置
# ============================================================
WEIGHTS = {"valuation": 0.30, "event": 0.25, "technical": 0.20, "trend": 0.15, "sentiment": 0.10}
VALUATION_WINDOW = 365 * 3
API_BASE = os.environ.get("OKX_API_BASE", "https://www.oyigwcn.biz")

# 重大事件日期（手动添加，如 X Layer 升级、Jumpstart、合作公告等）
# 注意：2025年8月后 OKB 已永久固定总量2100万，不再有季度销毁！
# 有新催化事件时手动添加日期，格式 "YYYY-MM-DD"
EVENT_DATES = [
    "2025-08-18",  # 历史：超级销毁（已落地，仅作记录）
    # 示例："2026-XX-XX",  # X Layer 重大升级 / Jumpstart 等
]

# ============================================================
# 邮件推送配置（信号变化时自动发邮件）
# 优先从环境变量读取（GitHub Actions 用 Secrets），本地运行可直接改下面默认值
# ============================================================
EMAIL_CONFIG = {
    "enabled": os.environ.get("EMAIL_ENABLED", "true").lower() == "true",
    "smtp_server": os.environ.get("EMAIL_SMTP_SERVER", "smtp.qq.com"),
    "smtp_port": int(os.environ.get("EMAIL_SMTP_PORT", "465")),
    "use_ssl": os.environ.get("EMAIL_USE_SSL", "true").lower() == "true",
    "sender": os.environ.get("EMAIL_SENDER", "5660597@qq.com"),
    "password": os.environ.get("EMAIL_PASSWORD", ""),
    "receivers": [r.strip() for r in os.environ.get("EMAIL_RECEIVERS", "5660597@qq.com").split(",") if r.strip()],
}


# ============================================================
# 数据获取
# ============================================================
def fetch_candles(inst_id, bar="1D", target_days=1095):
    """分页获取历史K线（OKX单次最多300条，用after参数翻旧页）"""
    all_rows = []
    after_ts = None
    max_pages = target_days // 300 + 2

    for _ in range(max_pages):
        url = f"{API_BASE}/api/v5/market/candles"
        params = {"instId": inst_id, "bar": bar, "limit": "300"}
        if after_ts:
            params["after"] = str(after_ts)
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json().get("data", [])
        if not data:
            break
        for r in data:
            all_rows.append({
                "ts": datetime.fromtimestamp(int(r[0]) / 1000),
                "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": float(r[4]),
                "volume": float(r[5]),
            })
        after_ts = int(data[-1][0])
        if len(data) < 300:
            break

    if not all_rows:
        raise RuntimeError(f"获取 {inst_id} K线失败")
    all_rows.sort(key=lambda x: x["ts"])
    # 去重
    seen = set()
    unique = []
    for r in all_rows:
        k = r["ts"]
        if k not in seen:
            seen.add(k)
            unique.append(r)
    return unique


def fetch_funding_rate(inst_id="OKB-USDT-SWAP"):
    url = f"{API_BASE}/api/v5/public/funding-rate"
    params = {"instId": inst_id}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json().get("data", [])
    if not data:
        return 0.0001
    return float(data[0]["fundingRate"])


# ============================================================
# 邮件推送
# ============================================================
def send_email(subject, body):
    """发送邮件通知。失败时打印错误但不中断主流程。"""
    cfg = EMAIL_CONFIG
    if not cfg.get("enabled"):
        return False
    if not cfg.get("sender") or not cfg.get("password") or not cfg.get("receivers"):
        print("  [邮件] 配置不完整，跳过发送")
        return False

    import smtplib
    from email.mime.text import MIMEText
    from email.header import Header
    from email.utils import formataddr

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr((str(Header("OKB信号监控", "utf-8")), cfg["sender"]))
    msg["To"] = ", ".join(cfg["receivers"])
    msg["Subject"] = Header(subject, "utf-8")

    try:
        if cfg.get("use_ssl", True):
            server = smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"], timeout=15)
        else:
            server = smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"], timeout=15)
            server.starttls()
        server.login(cfg["sender"], cfg["password"])
        server.sendmail(cfg["sender"], cfg["receivers"], msg.as_string())
        server.quit()
        print(f"  [邮件] 已发送至 {', '.join(cfg['receivers'])}")
        return True
    except Exception as e:
        print(f"  [邮件] 发送失败: {e}")
        return False


def build_signal_email(prev_action, prev_score, action, total, factors, okb_price, btc_price):
    """构建信号变化邮件内容。"""
    is_buy = "买入" in action
    emoji = "🟢" if is_buy else "🔴"
    subject = f"{emoji} OKB/BTC信号变化: {prev_action}({prev_score:.1f}) → {action}({total:.1f})"

    lines = [
        f"OKB/BTC 五因子信号变化提醒",
        f"{'='*40}",
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"信号变化: {prev_action} ({prev_score:.1f}分) → {action} ({total:.1f}分)",
        f"建议操作: {action}",
        f"",
        f"当前行情:",
        f"  OKB/BTC: {okb_price:.6f}  (≈ ${okb_price*btc_price:.2f})",
        f"  BTC/USDT: ${btc_price:,.0f}",
        f"",
        f"五因子详情:",
        f"  估值(30%): {factors['valuation']['score']:.1f}分 - {factors['valuation']['desc']}",
        f"  事件(25%): {factors['event']['score']:.1f}分 - {factors['event']['desc']}",
        f"  技术(20%): {factors['technical']['score']:.1f}分 - {factors['technical']['desc']}",
        f"  趋势(15%): {factors['trend']['score']:.1f}分 - {factors['trend']['desc']}",
        f"  情绪(10%): {factors['sentiment']['score']:.1f}分 - {factors['sentiment']['desc']}",
        f"",
        f"{'='*40}",
        f"本邮件由 OKB/BTC 信号监控脚本自动发送",
        f"仅供研究参考，不构成投资建议",
    ]
    return subject, "\n".join(lines)




def build_daily_email(action, total, position, factors, okb_price, btc_price, prev_signal):
    """构建每日状态报告邮件。"""
    is_buy = "买入" in action
    is_sell = "卖出" in action or "减仓" in action
    if is_buy:
        emoji = "🟢"
    elif is_sell:
        emoji = "🔴"
    else:
        emoji = "🟡"

    subject = f"{emoji} OKB/BTC每日报告: {action}({total:.1f}分)"

    if prev_signal:
        prev_line = f"上次信号: {prev_signal.get('action','?')} ({prev_signal.get('score',0):.1f}分)"
    else:
        prev_line = "首次运行"

    lines = [
        f"OKB/BTC 五因子每日状态报告",
        f"{'='*40}",
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"{prev_line}",
        f"",
        f"当前信号: {action} ({total:.1f}分)",
        f"仓位建议: {position}",
        f"",
        f"当前行情:",
        f"  OKB/BTC: {okb_price:.6f}  (≈ ${okb_price*btc_price:.2f})",
        f"  BTC/USDT: ${btc_price:,.0f}",
        f"",
        f"五因子详情:",
        f"  估值(30%): {factors['valuation']['score']:.1f}分 - {factors['valuation']['desc']}",
        f"  事件(25%): {factors['event']['score']:.1f}分 - {factors['event']['desc']}",
        f"  技术(20%): {factors['technical']['score']:.1f}分 - {factors['technical']['desc']}",
        f"  趋势(15%): {factors['trend']['score']:.1f}分 - {factors['trend']['desc']}",
        f"  情绪(10%): {factors['sentiment']['score']:.1f}分 - {factors['sentiment']['desc']}",
        f"",
        f"{'='*40}",
        f"本邮件由 OKB/BTC 信号监控脚本自动发送（每日中午12点）",
        f"仅供研究参考，不构成投资建议",
    ]
    return subject, "\n".join(lines)

# ============================================================
# 技术指标
# ============================================================
def calc_rsi(closes, period=14):
    n = len(closes)
    rsi = np.full(n, 50.0)
    if n < period + 1:
        return rsi
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    rsi[period] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rsi[i] = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi


def calc_ma(values, period):
    n = len(values)
    ma = np.full(n, np.nan)
    for i in range(period - 1, n):
        ma[i] = np.mean(values[i - period + 1:i + 1])
    return ma


# ============================================================
# 五因子
# ============================================================
def factor_valuation(rows):
    closes = np.array([r["close"] for r in rows])
    n = len(closes)
    window = min(VALUATION_WINDOW, n)
    current = closes[-1]
    lookback = closes[max(0, n - window):-1]
    percentile = np.mean(lookback < current) if len(lookback) > 0 else 0.5
    score = float(np.clip((1 - percentile) * 100, 0, 100))
    return {
        "score": round(score, 1),
        "desc": f"比率 {current:.6f} BTC，近{len(lookback)}天 {percentile*100:.0f}% 分位",
    }


def factor_event():
    """
    事件因子：手动添加的重大事件（X Layer升级、Jumpstart、合作公告等）。
    2025年8月后 OKB 总量永久固定2100万，不再有季度销毁，
    因此无手动添加事件时默认中性40分。
    """
    now = datetime.now()
    events = [datetime.strptime(d, "%Y-%m-%d") for d in EVENT_DATES]
    events = [e for e in events if not np.isnan(e.year)]
    future = sorted([e for e in events if e > now])
    next_event = future[0] if future else None

    # 事件后3天内（卖事实）
    for e in events:
        if e <= now and (now - e).days <= 3:
            return {"score": 10, "desc": "事件刚落地1-3天（卖事实）", "next": fmt(next_event)}

    if not next_event:
        return {"score": 40, "desc": "无待落地事件（2025.8后已无季度销毁，需手动添加催化事件）", "next": "无"}

    days = (next_event - now).days
    if days <= 3:
        return {"score": 50, "desc": f"距事件 {days} 天，落地前夕", "next": fmt(next_event)}
    elif days <= 14:
        return {"score": 70, "desc": f"距事件 {days} 天，预期升温期", "next": fmt(next_event)}
    elif days <= 28:
        return {"score": 90, "desc": f"距事件 {days} 天，提前布局窗口", "next": fmt(next_event)}
    else:
        return {"score": 40, "desc": f"距下一事件 {days} 天，空窗期", "next": fmt(next_event)}


def factor_technical(rows):
    closes = np.array([r["close"] for r in rows])
    volumes = np.array([r["volume"] for r in rows])
    n = len(closes)
    rsi = calc_rsi(closes)
    ma50 = calc_ma(closes, 50)
    vol_ma20 = calc_ma(volumes, 20)

    # 布林带
    period = 20
    bb_upper = np.full(n, np.nan)
    bb_lower = np.full(n, np.nan)
    for i in range(period - 1, n):
        slice_ = closes[i - period + 1:i + 1]
        m = np.mean(slice_)
        sd = np.std(slice_)
        bb_upper[i] = m + 2 * sd
        bb_lower[i] = m - 2 * sd

    idx = n - 1
    current_rsi = rsi[idx]
    price = closes[idx]

    rsi_score = float(np.clip((70 - current_rsi) / 35 * 100, 0, 100))

    if not np.isnan(bb_upper[idx]) and bb_upper[idx] > bb_lower[idx]:
        bb_pos = (price - bb_lower[idx]) / (bb_upper[idx] - bb_lower[idx])
        bb_score = float(np.clip((1 - bb_pos) * 100, 0, 100))
    else:
        bb_score = 50.0

    if not np.isnan(ma50[idx]):
        dev = (price - ma50[idx]) / ma50[idx]
        ma_score = float(np.clip((0.25 - dev) / 0.40 * 100, 0, 100))
    else:
        ma_score = 50.0

    if not np.isnan(vol_ma20[idx]) and vol_ma20[idx] > 0:
        ratio = volumes[idx] / vol_ma20[idx]
        vol_score = float(np.clip((3.0 - ratio) / 2.4 * 100, 0, 100))
    else:
        vol_score = 50.0

    total = (rsi_score + bb_score + ma_score + vol_score) / 4
    ma_dev = f"{(price/ma50[idx]-1)*100:.1f}%" if not np.isnan(ma50[idx]) else "N/A"
    vol_ratio = f"{volumes[idx]/vol_ma20[idx]:.2f}" if not np.isnan(vol_ma20[idx]) else "N/A"
    return {
        "score": round(total, 1),
        "desc": f"RSI {current_rsi:.1f} | MA50偏离 {ma_dev} | 量比 {vol_ratio}",
    }


def factor_trend(btc_rows):
    closes = np.array([r["close"] for r in btc_rows])
    n = len(closes)
    ma50 = calc_ma(closes, 50)
    ma200 = calc_ma(closes, 200)
    idx = n - 1
    price = closes[idx]

    if np.isnan(ma200[idx]):
        return {"score": 40, "desc": "BTC数据不足200天", "btc_price": price}

    if price > ma200[idx] and ma50[idx] > ma200[idx]:
        return {"score": 100, "desc": "BTC多头排列", "btc_price": price}
    elif price > ma200[idx]:
        return {"score": 70, "desc": "BTC在MA200上方", "btc_price": price}
    elif price > ma200[idx] * 0.95:
        return {"score": 40, "desc": "BTC在MA200附近震荡", "btc_price": price}
    elif ma50[idx] > ma200[idx]:
        return {"score": 10, "desc": "BTC跌破MA200", "btc_price": price}
    else:
        return {"score": 0, "desc": "BTC空头排列", "btc_price": price}


def factor_sentiment(rate):
    score = float(np.clip((0.001 - rate) / 0.0015 * 100, 0, 100))
    rate_pct = rate * 100
    if rate < -0.0005:
        desc = f"费率 {rate_pct:.4f}%，偏悲观"
    elif rate > 0.0008:
        desc = f"费率 {rate_pct:.4f}%，偏狂热"
    else:
        desc = f"费率 {rate_pct:.4f}%，中性"
    return {"score": round(score, 1), "desc": desc}


# ============================================================
# 综合信号
# ============================================================
def combine(factors):
    total = sum(factors[k]["score"] * WEIGHTS[k] for k in WEIGHTS)
    if total >= 80:
        return total, "买入", "建议仓位 60-80%", "green"
    elif total >= 70:
        return total, "买入", "建议仓位 40-60%", "green"
    elif total >= 55:
        return total, "观望偏多", "建议仓位 20-40%", "yellow"
    elif total >= 40:
        return total, "持有/观望", "建议仓位 0-20%", "yellow"
    elif total >= 25:
        return total, "减仓", "建议减仓50%", "red"
    else:
        return total, "卖出", "建议清仓换回BTC", "red"


def fmt(dt):
    return dt.strftime("%Y-%m-%d") if dt else "无"


def color_text(text, color):
    colors = {"green": "\033[92m", "red": "\033[91m", "yellow": "\033[93m",
              "bold": "\033[1m", "reset": "\033[0m"}
    return f"{colors.get(color, '')}{text}{colors['reset']}"


# ============================================================
# 主程序
# ============================================================
def main():
    print("=" * 55)
    print("  OKB/BTC 五因子信号查询")
    print("=" * 55)
    print(f"  查询时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if EMAIL_CONFIG.get("enabled"):
        print(f"  📧 邮件推送: 已启用 → {', '.join(EMAIL_CONFIG['receivers'])}")
    else:
        print(f"  📧 邮件推送: 未启用（修改 EMAIL_CONFIG.enabled=True 开启）")
    print()

    try:
        print("  正在获取近3年历史数据...")
        okb_rows = fetch_candles("OKB-BTC", "1D", 1095)
        btc_rows = fetch_candles("BTC-USDT", "1D", 1095)
        funding_rate = fetch_funding_rate()
    except Exception as e:
        print(f"\n  ❌ 数据获取失败: {e}")
        print(f"  请检查网络是否可访问 {API_BASE}")
        return

    last = okb_rows[-1]
    btc_price = btc_rows[-1]["close"]
    print(f"  数据范围: {okb_rows[0]['ts'].strftime('%Y-%m-%d')} ~ {okb_rows[-1]['ts'].strftime('%Y-%m-%d')} ({len(okb_rows)}天)")
    print(f"  OKB/BTC: {last['close']:.6f}  (≈ ${last['close']*btc_price:.2f})")
    print(f"  BTC/USDT: ${btc_price:,.0f}")
    print()

    # 计算因子
    factors = {
        "valuation": factor_valuation(okb_rows),
        "event": factor_event(),
        "technical": factor_technical(okb_rows),
        "trend": factor_trend(btc_rows),
        "sentiment": factor_sentiment(funding_rate),
    }

    total, action, position, color = combine(factors)

    # 信号变化检测
    import json, os
    signal_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".okb_last_signal.json")
    prev_signal = None
    if os.path.exists(signal_file):
        try:
            with open(signal_file) as f:
                prev_signal = json.load(f)
        except Exception:
            pass
    with open(signal_file, "w") as f:
        json.dump({"action": action, "score": total, "time": datetime.now().isoformat()}, f)

    if prev_signal and prev_signal.get("action") != action:
        is_buy = "买入" in action
        is_sell = "卖出" in action or "减仓" in action
        if is_buy or is_sell:
            print()
            print("  " + "=" * 50)
            print(f"  ⚡ 信号变化: {prev_signal['action']} ({prev_signal['score']:.1f}分) → {action} ({total:.1f}分)")
            print("  " + "=" * 50)
            print()
            # 邮件推送
            if EMAIL_CONFIG.get("enabled"):
                subject, body = build_signal_email(
                    prev_signal["action"], prev_signal["score"],
                    action, total, factors, last["close"], btc_price
                )
                send_email(subject, body)

    # 每日状态报告（无论信号是否变化都发送）
    daily_report = os.environ.get("DAILY_REPORT", "false").lower() == "true"
    if daily_report and EMAIL_CONFIG.get("enabled"):
        print("  正在发送每日状态报告邮件...")
        d_subject, d_body = build_daily_email(
            action, total, position, factors, last["close"], btc_price, prev_signal
        )
        send_email(d_subject, d_body)

    # 输出
    print("-" * 55)
    print(f"  【当前信号】 {color_text(action, color)} {color_text(f'({total:.1f}分)', 'bold')}")
    print(f"  {position}")
    print("-" * 55)
    print()

    names = [
        ("valuation", "估值因子", "30%"),
        ("event", "事件因子", "25%"),
        ("technical", "技术因子", "20%"),
        ("trend", "趋势因子", "15%"),
        ("sentiment", "情绪因子", "10%"),
    ]
    for key, name, weight in names:
        f = factors[key]
        sc = f["score"]
        bar_len = int(sc / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        c = "green" if sc >= 60 else ("yellow" if sc >= 40 else "red")
        print(f"  {name}({weight}) {color_text(bar, c)} {sc:5.1f}")
        print(f"         {f['desc']}")
        print()

    print("=" * 55)
    print("  估值30% · 事件25% · 技术20% · 趋势15% · 情绪10%")
    print("  仅供研究参考，不构成投资建议")
    print("=" * 55)


if __name__ == "__main__":
    import sys
    if "--test-email" in sys.argv:
        print("测试邮件发送...")
        ok = send_email(
            "OKB/BTC 邮件推送测试",
            f"这是一封测试邮件。\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"如果你收到这封邮件，说明邮件推送配置成功！\n\n"
            f"当前配置:\n  SMTP: {EMAIL_CONFIG['smtp_server']}:{EMAIL_CONFIG['smtp_port']}\n"
            f"  发件人: {EMAIL_CONFIG['sender']}\n  收件人: {', '.join(EMAIL_CONFIG['receivers'])}"
        )
        if ok:
            print("✅ 测试邮件发送成功！")
        else:
            print("❌ 测试邮件发送失败，请检查配置。")
        sys.exit(0)
    main()
