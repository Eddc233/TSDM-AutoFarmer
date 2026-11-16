import os
import re
import sys
import time

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.tsdm39.com"
COOKIE = os.environ.get("TSDM_COOKIE", "").strip()

if not COOKIE:
    raise SystemExit("缺少环境变量 TSDM_COOKIE")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cookie": COOKIE,
}


def short_response(response):
    """只输出有限且脱敏的诊断信息，不输出 Cookie 或完整页面。"""
    text = response.text or ""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = BeautifulSoup(title_match.group(1), "html.parser").get_text(" ", strip=True) if title_match else "(无 title)"
    return (
        f"HTTP={response.status_code}, URL={response.url}, "
        f"Content-Type={response.headers.get('content-type', '未知')}, "
        f"title={title[:100]!r}, body长度={len(text)}"
    )


def extract_formhash(html):
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one('input[name="formhash"]')
    if node and node.get("value"):
        return node["value"]

    patterns = [
        r"name=[\"']formhash[\"'][^>]*value=[\"']([^\"']+)[\"']",
        r"value=[\"']([^\"']+)[\"'][^>]*name=[\"']formhash[\"']",
        r"[?&]formhash=([a-zA-Z0-9]+)",
        r"formhash=([a-zA-Z0-9]+)[\"'&\s]",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return match.group(1)
    return None


def tsdm_check_in(client):
    print("【签到】正在获取论坛首页和 formhash……")
    response = client.get(f"{BASE}/forum.php")
    print("【签到页面】" + short_response(response))

    formhash = extract_formhash(response.text)
    if not formhash:
        print("【签到结果】❌ 页面中没有找到 formhash。")
        print("【诊断】检查最终 URL、HTTP 状态码和 title；可能是登录跳转、验证页或页面结构变化。")
        return False

    print("【签到】已提取 formhash（值已隐藏），提交签到请求……")
    payload = {
        "formhash": formhash,
        "qdxq": "kx",
        "qdmode": "3",
        "todaysay": "",
        "fastreply": "1",
    }
    response = client.post(
        f"{BASE}/plugin.php?id=dsu_paulsign:sign&operation=qiandao&infloat=1&sign_as=1&inajax=1",
        data=payload,
        headers={"Referer": f"{BASE}/forum.php", "X-Requested-With": "XMLHttpRequest"},
    )
    print("【签到响应】" + short_response(response))

    body = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
    if "签到成功" in body:
        print("【签到结果】✅ 服务器响应包含“签到成功”。")
        return True
    if "已经签到" in body or "今日已签到" in body or "今天已经签到" in body:
        print("【签到结果】ℹ️ 服务器提示今天已经签到。")
        return True

    print("【签到结果】⚠️ 未识别到明确成功提示，不能判定签到成功。")
    print("【签到响应摘要】" + body[:240])
    return False


def tsdm_work(client):
    page_url = f"{BASE}/plugin.php?id=np_cliworkdz:work"
    print("【打工】正在查询打工页面……")
    response = client.get(
        f"{page_url}&inajax=1",
        headers={"Referer": page_url, "X-Requested-With": "XMLHttpRequest"},
    )
    print("【打工页面】" + short_response(response))

    body = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
    cooldown = re.search(r"您需要等待\s*\d+\s*小时\s*\d+\s*分钟\s*\d+\s*秒后即可进行", body)
    if cooldown:
        print(f"【打工结果】⏳ {cooldown.group()}，本次不重复执行。")
        return False

    print("【打工】开始发送 6 次 clickad 请求……")
    for i in range(6):
        r = client.post(
            page_url,
            data={"act": "clickad"},
            headers={
                "Referer": page_url,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        print(f"【打工点击 {i + 1}/6】{short_response(r)}")
        time.sleep(3)

    print("【打工】发送领取奖励请求……")
    reward = client.post(
        page_url,
        data={"act": "getcre"},
        headers={
            "Referer": page_url,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    print("【打工奖励响应】" + short_response(reward))
    reward_text = BeautifulSoup(reward.text, "html.parser").get_text(" ", strip=True)
    print("【打工奖励摘要】" + reward_text[:240])
    print("【打工结果】⚠️ 请求已发送；需结合奖励响应及天使币变化确认是否真正完成。")
    return True


def get_score(client):
    try:
        response = client.get(
            f"{BASE}/home.php?mod=spacecp&ac=credit&showcredit=1",
            headers={"Referer": f"{BASE}/forum.php"},
        )
        print("【天使币页面】" + short_response(response))
        soup = BeautifulSoup(response.text, "html.parser")

        ul = soup.select_one("ul.creditl")
        if ul:
            li = ul.select_one("li.xi1")
            if li:
                return li.get_text(" ", strip=True).replace("天使币:", "").replace("天使币：", "").strip()

        match = re.search(r"天使币\s*[:：]\s*([\d,]+)", soup.get_text(" ", strip=True))
        if match:
            return match.group(1)

        print("【天使币】⚠️ 未找到旧版 creditl 结构，也未匹配到天使币文本。")
        return "未知"
    except Exception as exc:
        print(f"【天使币查询异常】{type(exc).__name__}: {exc}")
        return "未知"


def main():
    task = sys.argv[1].lower() if len(sys.argv) > 1 else "both"
    if task not in ("checkin", "work", "both"):
        raise SystemExit("用法：python tsdm.py [checkin|work|both]")

    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        if task in ("checkin", "both"):
            tsdm_check_in(client)
        if task in ("work", "both"):
            tsdm_work(client)
        print("【当前天使币】" + get_score(client))


if __name__ == "__main__":
    main()
