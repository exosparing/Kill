import os
import re
import sqlite3
import requests
import threading
from io import StringIO
from flask import Flask, redirect, url_for, session, request, render_template_string, make_response
from datetime import datetime, timedelta
import discord
from discord import app_commands

app = Flask(__name__)
app.secret_key = "secure_dashboard_secret_key_string_!@#$"

# ✅ 세션 보안 설정
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
app.config['SESSION_COOKIE_SECURE'] = True

# =========================================================================
# ✅ 환경변수 또는 직접 값 입력 (여기에 네 값 채우기)
# =========================================================================
CLIENT_ID = os.getenv("CLIENT_ID", "1538907966218969088")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "aO0ozPtvlcVyrMhUo9btQyrsNdqZUwcp")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1537897347890028724/e2KU2TD-l-A9C0FuABr8HK7VHa5Gzu_FYyzmKIkZqe5hcvOaTiH_xjMoN9bF9EPSuJ5i")
GUILD_ID = int(os.getenv("GUILD_ID", "1537869964554281020"))
VERIFY_ROLE_ID = int(os.getenv("VERIFY_ROLE_ID", "1537896063812247674"))
ADMIN_DISCORD_ID = "1513116439563997264"  # ← 너의 디스코드 ID 숫자로
REDIRECT_URI = "https://kill-xqmz.onrender.com/callback"

DISCORD_API = "https://discord.com/api/v10"

# =========================================================================
# ✅ VPN / 프록시 / 호스팅 IP 전부 차단
# =========================================================================
def is_vpn_or_proxy(ip):
    """IP가 VPN/프록시/호스팅이면 True 반환 — 인증 차단"""
    try:
        # 1. IP 확인 API (무료, 속도 빠름)
        r = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5)
        if r.status_code != 200:
            return False
        data = r.json()

        # ✅ 호스팅·데이터센터이면 차단
        org = data.get("org", "").lower()
        hosting_keywords = [
            "amazon", "google", "microsoft", "azure", "linode", "digitalocean",
            "vultr", "hetzner", "ovh", "scaleway", "alibaba", "tencent",
            "hosting", "datacenter", "server", "vps", "cloud", "host",
            "contabo", "netcup", "dreamhost", "bluehost", "hostgator",
            "vpnbg", "nordvpn", "expressvpn", "surfshark", "protonvpn",
            "mullvad", "windscribe", "torguard", "ipvanish", "purevpn",
            "cyberghost", "privateinternetaccess", "strongvpn", "hide.me",
            "bolehvpn", "ivpn", "airvpn", "vpn", "proxy", "relay"
        ]
        for kw in hosting_keywords:
            if kw in org:
                return True

        # ✅ IP 유형 확인 — 호스팅이면 차단
        r2 = requests.get(f"https://api.ipify.org/geo?ip={ip}", timeout=5)
        if r2.status_code == 200:
            d2 = r2.json()
            if d2.get("type") in ["hosting", "datacenter", "vpn", "proxy"]:
                return True

        return False

    except Exception as e:
        print(f"VPN 확인 오류: {e}")
        return False

# =========================================================================
# ✅ 디스코드 봇 설정
# =========================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

@tree.command(name="verify", description="서버 인증을 진행합니다")
async def verify(interaction: discord.Interaction):
    auth_url = REDIRECT_URI.replace("/callback", "/")
    embed = discord.Embed(
        title="🔒 서버 인증",
        description="아래 버튼을 눌러 인증을 완료해주세요!\n인증하면 자동으로 역할이 부여됩니다!\n⚠️ VPN/프록시 사용시 인증이 차단됩니다.",
        color=discord.Color.green()
    )
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="✅ 인증하러 가기", url=auth_url, style=discord.ButtonStyle.link))
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"✅ 봇 온라인: {bot.user}")

# =========================================================================
# ✅ 데이터베이스 초기화
# =========================================================================
def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT UNIQUE,
        email TEXT,
        ip TEXT,
        country TEXT,
        org TEXT,
        verified_at TEXT,
        blocked INTEGER DEFAULT 0
    )""")
    conn.commit()
    conn.close()

init_db()

# =========================================================================
# ✅ 웹 인증 라우트
# =========================================================================
@app.route("/")
def index():
    if "discord_id" in session:
        return redirect(url_for("dashboard"))
    auth_url = f"{DISCORD_API}/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify%20email"
    return redirect(auth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "인증 실패", 400

    ip = request.remote_addr

    # ✅ VPN/프록시 검사 — 차단
    if is_vpn_or_proxy(ip):
        # 차단된 IP 정보 관리자에게 전송
        if DISCORD_WEBHOOK_URL:
            requests.post(DISCORD_WEBHOOK_URL, json={
                "embeds": [{
                    "title": "🚫 VPN/프록시 차단됨",
                    "fields": [
                        {"name": "IP", "value": f"`{ip}`", "inline": False},
                        {"name": "시간", "value": datetime.now().isoformat(), "inline": False}
                    ],
                    "color": 15548997
                }]
            })
        return render_template_string("""
        <h2>🚫 인증이 차단되었습니다</h2>
        <p>VPN, 프록시, 호스팅 IP에서는 인증할 수 없습니다.</p>
        <p>일반 가정용 인터넷으로 다시 시도해주세요.</p>
        """)

    # 토큰 받기
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(f"{DISCORD_API}/oauth2/token", data=data, headers=headers)
    if r.status_code != 200:
        return f"토큰 오류: {r.text}", 400
    token = r.json().get("access_token")

    # 유저 정보 받기
    me = requests.get(f"{DISCORD_API}/users/@me", headers={"Authorization": f"Bearer {token}"}).json()
    discord_id = me["id"]
    email = me.get("email", "비공개")

    # IP 정보 조회
    ipinfo = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5).json()
    country = ipinfo.get("country", "알수없음")
    org = ipinfo.get("org", "알수없음")

    # DB에 저장
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    try:
        c.execute("""INSERT OR REPLACE INTO users 
            (discord_id, email, ip, country, org, verified_at, blocked)
            VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (discord_id, email, ip, country, org, datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        print(f"DB 오류: {e}")
    conn.close()

    # ✅ 관리자에게 정보 전송
    webhook_data = {
        "embeds": [{
            "title": "✅ 새 인증 유저",
            "fields": [
                {"name": "디스코드 ID", "value": f"`{discord_id}`", "inline": False},
                {"name": "이메일", "value": f"`{email}`", "inline": False},
                {"name": "IP 주소", "value": f"`{ip}`", "inline": False},
                {"name": "국가", "value": f"`{country}`", "inline": True},
                {"name": "인터넷 제공사", "value": f"`{org}`", "inline": True}
            ],
            "color": 5763719
        }]
    }
    if DISCORD_WEBHOOK_URL:
        requests.post(DISCORD_WEBHOOK_URL, json=webhook_data)

    # ✅ 역할 부여
    guild = bot.get_guild(GUILD_ID)
    if guild:
        member = guild.get_member(int(discord_id))
        if member:
            role = guild.get_role(VERIFY_ROLE_ID)
            if role:
                try:
                    member.add_roles(role)
                except Exception as e:
                    print(f"역할 부여 오류: {e}")

    session["discord_id"] = discord_id
    return redirect(url_for("dashboard"))

@app.route("/dashboard")
def dashboard():
    if "discord_id" not in session:
        return redirect(url_for("index"))
    discord_id = session["discord_id"]

    # ✅ 관리자만 IP·이메일 전부 보임
    IS_ADMIN = str(discord_id) == ADMIN_DISCORD_ID

    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT discord_id, email, ip, country, org, verified_at FROM users WHERE discord_id=?", (discord_id,))
    u = c.fetchone()
    conn.close()

    if not u:
        return redirect(url_for("index"))

    display_ip = "🔒 관리자에게만 공개" if not IS_ADMIN else u[2]
    display_email = "🔒 관리자에게만 공개" if not IS_ADMIN else u[1]

    return render_template_string("""
    <h2>✅ 인증 완료!</h2>
    <p><strong>디스코드 ID:</strong> {{did}}</p>
    <p><strong>이메일:</strong> {{email}}</p>
    <p><strong>IP 주소:</strong> {{ip}}</p>
    <p><strong>국가:</strong> {{country}}</p>
    <p>✅ 역할이 자동으로 부여되었습니다. 이제 디스코드로 돌아가세요!</p>
    <a href="/logout" style="color:blue;">로그아웃</a>
    """, did=discord_id, email=display_email, ip=display_ip, country=u[3])

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# =========================================================================
# ✅ 웹 + 봇 동시 실행
# =========================================================================
def run_web():
    app.run(host="0.0.0.0", port=5000, debug=False)

if __name__ == "__main__":
    print("✅ 인증 시스템 시작 중...")
    threading.Thread(target=run_web, daemon=True).start()
    bot.run(DISCORD_BOT_TOKEN)
