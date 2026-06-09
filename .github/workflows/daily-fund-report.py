#!/usr/bin/env python3
# Fund NAV daily monitor + DingTalk push (Cloud version)
# Reads fund config from fund-config.json

import json
import time
import hmac
import hashlib
import base64
import urllib.request
import urllib.parse
import ssl
import os

# ============ CONFIG ============
DING_SECRET = "SEC58f66fb36f0de03f1f705233789fc4a6c23919d12b4055be705f3c2c982a05e7"
DING_TOKEN  = "2f65acfca16629bf6a8ab3577fd9a08eecd5bc76ddba92842f636b805d81bb07"

# Read fund list from JSON config (single source of truth)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_config_path = os.path.join(os.path.dirname(_script_dir), "fund-config.json")
if not os.path.exists(_config_path):
    _config_path = "fund-config.json"

with open(_config_path, "r", encoding="utf-8") as f:
    FUNDS_RAW = json.load(f)

# Convert to tuple format used internally
FUNDS = [(f["code"], f["name"], float(f["cost"]), float(f["buyNav"]),
          float(f["stopPct"]), f.get("locked", False)) for f in FUNDS_RAW]

# ============ DINGTALK ============
def send_ding(msg):
    ts = str(int(time.time() * 1000))
    secret_enc = DING_SECRET.encode('utf-8')
    sign_raw = f"{ts}\n{DING_SECRET}".encode('utf-8')
    signature = base64.b64encode(hmac.new(secret_enc, sign_raw, hashlib.sha256).digest()).decode()
    sign_encoded = urllib.parse.quote(signature, safe='')
    url = f"https://oapi.dingtalk.com/robot/send?access_token={DING_TOKEN}&timestamp={ts}&sign={sign_encoded}"

    body = json.dumps({"msgtype": "text", "text": {"content": msg}}).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        return json.loads(resp.read()).get("errcode") == 0
    except:
        return False

# ============ GET NAV ============
def get_nav(code):
    # Primary: eastmoney API
    try:
        ts = int(time.time() * 1000)
        url = f"https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery&fundCode={code}&pageIndex=1&pageSize=2&_={ts}"
        req = urllib.request.Request(url, headers={"Referer": "https://fundf10.eastmoney.com/"})
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        content = resp.read().decode('utf-8')
        # remove jQuery callback wrapper
        json_str = content.replace("jQuery(", "").rsplit(")", 1)[0]
        data = json.loads(json_str)
        items = data.get("Data", {}).get("LSJZList", [])
        if items:
            return float(items[0]["DWJZ"]), items[0].get("JZZZL", "0")
    except:
        pass

    # Fallback: daily fund valuation API
    try:
        ts = int(time.time() * 1000)
        url = f"https://fundgz.1234567.com.cn/js/{code}.js?rt={ts}"
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(url, timeout=10, context=ctx)
        content = resp.read().decode('utf-8')
        json_str = content.replace("jsonpgz(", "").rsplit(")", 1)[0]
        data = json.loads(json_str)
        return float(data["gsz"]), data.get("gszzl", "0")
    except:
        return None, None

# ============ MAIN ============
if __name__ == "__main__":
    from datetime import datetime
    today = datetime.now().strftime("%m-%d %H:%M")

    lines = [
        "====================================",
        f"  📊 {today} 基金日报 (云端)",
        "====================================",
        ""
    ]

    alerts = []
    total_cost = 0.0
    total_value = 0.0
    ok = 0
    missed = []

    for code, name, cost, buy_nav, stop_pct, locked in FUNDS:
        total_cost += cost
        nav, growth = get_nav(code)

        if nav:
            shares = cost / buy_nav
            cur_value = round(shares * nav, 2)
            pnl = round(cur_value - cost, 2)
            pnl_pct = round((nav - buy_nav) / buy_nav * 100, 2)
            stop_nav = round(buy_nav * (1 + stop_pct), 4)
            dist_stop = round((nav - stop_nav) / stop_nav * 100, 2)
            total_value += cur_value

            if pnl >= 0:
                icon = "🟢"
            elif pnl_pct > -3:
                icon = "🟡"
            else:
                icon = "🔴"

            lk = " [锁定中]" if locked else ""
            growth_str = f" | 日涨跌 {growth}%" if growth else ""

            lines.append(f"{icon} {name} ({code}){lk}")
            lines.append(f"   净值 {nav}{growth_str}")
            lines.append(f"   盈亏 {pnl}元 ({pnl_pct}%) | 距止损 {dist_stop}%")

            if not locked and nav <= stop_nav:
                alerts.append(f"🚨🚨 {name} ({code}) 触发止损！净值{nav} ≤ 止损线{stop_nav}")
            if not locked and dist_stop <= 2:
                alerts.append(f"⚠️ {name} ({code}) 距止损仅{dist_stop}%，需关注！")

            ok += 1
        else:
            lines.append(f"❓ {name} ({code}) 净值获取失败")
            missed.append(code)
            total_value += cost

    total_pnl = round(total_value - total_cost, 2)
    total_pnl_pct = round((total_value - total_cost) / total_cost * 100, 2) if total_cost > 0 else 0

    lines.append("")
    lines.append("====================================")
    lines.append(f"💰 总持仓: {total_cost}元 -> {total_value}元")
    lines.append(f"📊 累计盈亏: {total_pnl}元 ({total_pnl_pct}%)")
    lines.append(f"✅ 净值获取: {ok}/{len(FUNDS)} 成功")
    lines.append("⚡ 云端执行 | 不依赖本地电脑")

    if alerts:
        lines.append("")
        lines.append("====================================")
        lines.append("🚨 警报信息:")
        for a in alerts:
            lines.append(f"  {a}")

    if missed:
        lines.append("")
        lines.append(f"⚠️ 未获取到净值: {', '.join(missed)}")

    msg_body = "\n".join(lines)
    print(msg_body)
    print()

    success = send_ding(msg_body)
    print("钉钉推送: 成功" if success else "钉钉推送: 失败")

    # Send separate alert if triggered
    if alerts:
        alert_body = "🚨 止损警报！\n\n" + "\n".join(alerts) + "\n\n请立即查看持仓并决策！"
        send_ding(alert_body)
