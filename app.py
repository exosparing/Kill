import os
import sqlite3
import requests
import threading
from flask import Flask, request, render_template_string
from datetime import datetime, timedelta
import discord
from discord import app_commands

print("✅ 1단계: import 완료!")

app = Flask(__name__)
app.secret_key = "secure_dashboard_secret_key_string_!@#$"

app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
app.config['SESSION_COOKIE_SECURE'] = True

print("✅ 2단계: Flask 설정 완료!")

CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ADMIN_WEBHOOK_URL = os.getenv("ADMIN_WEBHOOK_URL", "")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://kill-xqmz.onrender.com/callback")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
VERIFY_ROLE_ID = int(os.getenv("VERIFY_ROLE_ID", "0"))
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
ADMIN_DISCORD_ID = os.getenv("ADMIN_DISCORD_ID", "")

print(f"✅ 3단계: 환경변수 로드 완료! GUILD_ID={GUILD_ID}")

DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_API_URL = "https://discord.com/api/users/@me"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

print(f"✅ 4단계: discord.py 버전: {discord.__version__}")

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

print("✅ 5단계: 봇 객체 생성 완료!")

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
print("✅ 6단계: DB 초기화 완료!")

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
            body { font-family: sans-serif; text-align: center; padding-top: 80px; background: #2c2f33; color: white; }
            .btn { padding: 15px 30px; background: #5865f2; color: white; border: none; border-radius: 8px; font-size: 18px; cursor: pointer; text-decoration: none; display: inline-block; }
            .btn:hover { background: #4752c4; }
        </style>
    </head>
    <body>
        <h1>🔒 서버 인증 시스템</h1>
        <p>아래 버튼을 눌러 디스코드로 인증을 완료해주세요.</p>
        <a href="{{ auth_url }}" class="btn">✅ 디스코드로 인증하기</a>
    </body>
    </html>
    """, auth_url=auth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "인증 실패!", 400

    token_data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    token_res = requests.post(DISCORD_TOKEN_URL, data=token_data)
    if token_res.status_code != 200:
        return "토큰 오류!", 400
    access_token = token_res.json()["access_token"]

    headers = {"Authorization": f"Bearer {access_token}"}
    user_res = requests.get(DISCORD_API_URL, headers=headers)
    if user_res.status_code != 200:
        return "유저 정보 오류!", 400
    user = user_res.json()

    discord_id = user["id"]
    username = f"{user['username']}#{user['discriminator']}"
    email = user.get("email", "이메일 공개 안됨")
    ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
    verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    IS_ADMIN = str(discord_id) == str(ADMIN_DISCORD_ID)
    display_ip = ip_address if IS_ADMIN else "제공하지 않음"
    display_email = email if IS_ADMIN else "제공하지 않음"

    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    try:
        c.execute("""INSERT OR REPLACE INTO users 
            (discord_id, username, email, ip_address, verified_at)
            VALUES (?, ?, ?, ?, ?)""",
            (discord_id, username, email, ip_address, verified_at))
        conn.commit()
    except Exception as e:
        print("DB 오류:", e)
    conn.close()

    if DISCORD_WEBHOOK_URL:
        embed = {
            "title": "✅ 새로운 인증 완료",
            "color": 5763719,
            "fields": [
                {"name": "유저", "value": f"<@{discord_id}> ({username})", "inline": False},
                {"name": "디스코드 ID", "value": f"`{discord_id}`", "inline": False},
                {"name": "IP 주소", "value": display_ip, "inline": True},
                {"name": "이메일", "value": display_email, "inline": True},
                {"name": "인증 시간", "value": verified_at, "inline": False}
            ],
            "footer": {"text": "인증 시스템"}
        }
        requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})

    if ADMIN_WEBHOOK_URL:
        admin_embed = {
            "title": "🔐 관리자용 — 인증 상세 정보",
            "color": 15105550,
            "fields": [
                {"name": "유저", "value": f"<@{discord_id}> ({username})", "inline": False},
                {"name": "디스코드 ID", "value": f"`{discord_id}`", "inline": False},
                {"name": "IP 주소", "value": f"`{ip_address}`", "inline": True},
                {"name": "이메일", "value": f"`{email}`", "inline": True},
                {"name": "인증 시간", "value": verified_at, "inline": False}
            ],
            "footer": {"text": "관리자 전용 — 개인정보 포함"}
        }
        requests.post(ADMIN_WEBHOOK_URL, json={"embeds": [admin_embed]})

    async def give_role():
        try:
            guild = await bot.fetch_guild(GUILD_ID)
            member = await guild.fetch_member(int(discord_id))
            role = guild.get_role(VERIFY_ROLE_ID)
            if role:
                await member.add_roles(role)
                print(f"✅ {username} 에게 역할 부여 완료!")
        except Exception as e:
            print(f"❌ 역할 부여 오류: {e}")

    threading.Thread(target=lambda: bot.loop.create_task(give_role())).start()

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>인증 완료!</title>
        <style>
            body { font-family: sans-serif; text-align: center; padding-top: 80px; background: #2c2f33; color: white; }
            .ok { color: #43b581; font-size: 24px; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1 class="ok">✅ 인증 완료!</h1>
        <p>디스코드로 돌아가시면 역할이 부여되어 있을겁니다!</p>
    </body>
    </html>
    """)

@tree.command(name="verify", description="서버 인증을 진행합니다")
async def verify(interaction: discord.Interaction):
    print(f"✅ /verify 명령어 호출됨! 사용자: {interaction.user}")
    auth_url = "https://kill-xqmz.onrender.com/"
    embed = discord.Embed(
        title="🔒 서버 인증",
        description="아래 버튼을 눌러 인증을 완료해주세요!\n인증하면 자동으로 역할이 부여됩니다!",
        color=discord.Color.green()
    )
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="✅ 인증하러 가기", url=auth_url, style=discord.ButtonStyle.link))
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ✅ 핵심 변경: on_ready 안에서 Flask를 나중에 시작!
@bot.event
async def on_ready():
    print("\n" + "="*60)
    print(f"✅ ✅ ✅ 7단계: on_ready 실행! 봇 로그인 성공: {bot.user}")
    print(f"discord.py 버전: {discord.__version__}")
    
    # ✅ 봇이 완전히 준비된 다음에 Flask 시작!
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ Flask 쓰레드 시작 완료!")
    
    # ✅ 명령어 등록
    if GUILD_ID != 0:
        print(f"✅ 8단계: 서버 명령어 등록 시도 중... GUILD_ID={GUILD_ID}")
        try:
            guild = discord.Object(id=GUILD_ID)
            await tree.sync(guild=guild)
            print("✅ ✅ ✅ 9단계: /verify 서버 명령어 등록 완료!")
        except Exception as e:
            print(f"❌ 서버 명령어 등록 오류: {e}")
            print("✅ 글로벌 명령어로 다시 시도 중...")
            try:
                await tree.sync()
                print("✅ ✅ ✅ 9단계: /verify 글로벌 명령어 등록 완료! (최대 1시간 걸릴 수 있음)")
            except Exception as e2:
                print(f"❌ 글로벌 명령어 등록 오류: {e2}")
    else:
        print("⚠️ GUILD_ID가 0임! 글로벌 명령어로 등록 시도...")
        try:
            await tree.sync()
            print("✅ ✅ ✅ 9단계: /verify 글로벌 명령어 등록 완료!")
        except Exception as e:
            print(f"❌ 글로벌 명령어 등록 오류: {e}")
    
    print("="*60 + "\n")

def run_flask():
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("✅ 0단계: 프로그램 시작!")
    # ✅ 이제 bot.run()이 먼저 실행! Flask는 on_ready 안에서 나중에 시작!
    bot.run(DISCORD_BOT_TOKEN)
