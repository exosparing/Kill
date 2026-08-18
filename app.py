import os
import re
import sqlite3
import requests
import csv
from io import StringIO
import threading
from flask import Flask, redirect, url_for, session, request, render_template_string, make_response
from datetime import datetime, timedelta
import discord
from discord import app_commands

app = Flask(__name__)
app.secret_key = "secure_dashboard_secret_key_string_!@#$"

# ✅ 세션 보안 강화 설정
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
app.config['SESSION_COOKIE_SECURE'] = True

# =========================================================================
# ✅ 여기에 본인 정보 정확히 입력 (Render 환경변수에서 읽어옴)
# =========================================================================
CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
REDIRECT_URI = "https://kill-xqmz.onrender.com/callback"
GUILD_ID = 1537869964554281020
VERIFY_ROLE_ID = 1537896063812247674
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
ADMIN_DISCORD_ID = "1513116439563997264"
# =========================================================================

DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_API_URL = "https://discord.com/api/users/@me"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ✅ 데이터베이스 초기화
def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT UNIQUE,
        username TEXT,
        email TEXT,
        ip_address TEXT,
        verified_at TEXT,
        vpn_detected INTEGER DEFAULT 0
    )""")
    conn.commit()
    conn.close()

init_db()

# ✅ 인증 페이지
@app.route("/")
def home():
    auth_url = f"{DISCORD_AUTH_URL}?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify%20email"
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>서버 인증</title>
        <style>
            body { font-family: sans-serif; text-align: center; padding-top: 80px; background: #1a1a1a; color: white; }
            .btn { padding: 15px 30px; font-size: 18px; background: #5865F2; color: white; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; display: inline-block; }
            .btn:hover { background: #4752C4; }
        </style>
    </head>
    <body>
        <h1>🔒 서버 인증</h1>
        <p>아래 버튼을 눌러 디스코드로 인증해주세요.</p>
        <a href="{{ auth_url }}" class="btn">✅ 디스코드로 인증하기</a>
    </body>
    </html>
    """, auth_url=auth_url)

# ✅ 콜백 — 인증 후 처리
@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "인증 실패", 400

    # 토큰 교환
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": "identify email"
    }
    token_res = requests.post(DISCORD_TOKEN_URL, data=data)
    if token_res.status_code != 200:
        return "토큰 오류", 400
    access_token = token_res.json()["access_token"]

    # 유저 정보 가져오기
    headers = {"Authorization": f"Bearer {access_token}"}
    user_res = requests.get(DISCORD_API_URL, headers=headers)
    if user_res.status_code != 200:
        return "유저 정보 오류", 400
    user = user_res.json()

    discord_id = user["id"]
    username = f"{user['username']}#{user['discriminator']}"
    email = user.get("email", "")
    ip_address = request.remote_addr
    verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ✅ 관리자 확인
    IS_ADMIN = (discord_id == "관리자_디스코드_ID_여기에_적어")  # ✅ 관리자 본인 ID만 적어!

    # ✅ DB에 저장
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    try:
        c.execute("""INSERT OR REPLACE INTO users 
        (discord_id, username, email, ip_address, verified_at)
        VALUES (?, ?, ?, ?, ?)""", (discord_id, username, email, ip_address, verified_at))
        conn.commit()
    except Exception as e:
        print("DB 오류:", e)
    conn.close()

    # ✅ 디스코드 웹훅으로 관리자에게만 전송
    if DISCORD_WEBHOOK_URL:
        hidden_ip = "***.***.***.***" if not IS_ADMIN else ip_address
        hidden_email = "비공개" if not IS_ADMIN else email
        embed = {
            "title": "✅ 새 인증 완료",
            "color": 3066993,
            "fields": [
                {"name": "유저", "value": username, "inline": True},
                {"name": "디스코드 ID", "value": discord_id, "inline": True},
                {"name": "IP (관리자만 보임)", "value": hidden_ip, "inline": False},
                {"name": "이메일 (관리자만 보임)", "value": hidden_email, "inline": False},
                {"name": "인증 시간", "value": verified_at, "inline": False}
            ]
        }
        requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})

    # ✅ 디스코드로 역할 부여
    @bot.event
    async def grant_role():
        try:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                member = await guild.fetch_member(int(discord_id))
                if member:
                    role = guild.get_role(VERIFY_ROLE_ID)
                    if role:
                        await member.add_roles(role)
                        print(f"✅ {username} 에게 역할 부여 완료")
        except Exception as e:
            print("역할 부여 오류:", e)

    bot.loop.create_task(grant_role())

    # ✅ 인증 완료 페이지
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>인증 완료</title>
        <style>
            body { font-family: sans-serif; text-align: center; padding-top: 80px; background: #1a1a1a; color: white; }
            .ok { color: #00ff99; font-size: 24px; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1 class="ok">✅ 인증 완료!</h1>
        <p>서버로 돌아가시면 역할이 부여되어 있습니다!</p>
    </body>
    </html>
    """)

# ✅ /verify 명령어 — 인증 버튼 보여주기
@tree.command(name="verify", description="서버 인증을 진행합니다")
async def verify(interaction: discord.Interaction):
    auth_url = "https://kill-xqmz.onrender.com/"
    embed = discord.Embed(
        title="🔒 서버 인증",
        description="아래 버튼을 눌러 인증을 완료해주세요!\n인증하면 자동으로 역할이 부여됩니다!",
        color=discord.Color.green()
    )
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="✅ 인증하러 가기", url=auth_url, style=discord.ButtonStyle.link))
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ✅ 봇 준비 완료 — 명령어 자동 동기화
@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print("="*50)
    print(f"✅ 봇 온라인: {bot.user}")
    print(f"✅ 명령어 동기화 완료! /verify 사용 가능!")
    print("="*50)

# ✅ 웹 실행
def run_web():
    app.run(host="0.0.0.0", port=10000)

# ✅ 동시 실행
threading.Thread(target=run_web, daemon=True).start()
bot.run(DISCORD_BOT_TOKEN)
