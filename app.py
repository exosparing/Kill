import os
import re
import sqlite3
import requests
from flask import Flask, redirect, url_for, session, request, render_template_string
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secure_dashboard_secret_key_string_!@#$"

# =========================================================================
# ✅ [여기를 본인 정보로 정확히 채우세요!]
# =========================================================================
CLIENT_ID = "여기에_디스코드_CLIENT_ID_입력"
CLIENT_SECRET = "여기에_디스코드_CLIENT_SECRET_입력"
DISCORD_WEBHOOK_URL = "여기에_관리자_채널_웹훅_URL_입력"
REDIRECT_URI = "https://kill-xmrr.onrender.com/callback"
# =========================================================================

# ✅ 디스코드 OAuth2 공식 주소
DISCORD_AUTH_URL = (
    f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify&prompt=consent"
)
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"

# ✅ 데이터베이스 초기화
def init_db():
    conn = sqlite3.connect("management.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS verified_users (
            discord_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            ip_address TEXT,
            isp TEXT,
            location TEXT,
            user_agent TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# ✅ 유저 정보 DB 저장
def save_user_to_db(user_data, ip, isp, location, ua):
    conn = sqlite3.connect("management.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO verified_users (discord_id, username, ip_address, isp, location, user_agent)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET
            username = excluded.username,
            ip_address = excluded.ip_address,
            isp = excluded.isp,
            location = excluded.location,
            user_agent = excluded.user_agent
    ''', (user_data['id'], user_data['username'], ip, isp, location, ua))
    conn.commit()
    conn.close()

# ✅ 관리자 디스코드 웹훅 알림 전송
def send_admin_webhook(user_data, ip, isp, location, user_agent, is_vpn=False):
    if not DISCORD_WEBHOOK_URL or "여기에_" in DISCORD_WEBHOOK_URL:
        return
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if is_vpn:
        title = "🚨 [우회 감지] VPN/프록시 접속 시도"
        color = 15158332
    else:
        title = "🔔 새로운 유저 인증 완료"
        color = 3447003

    embed = {
        "title": title,
        "color": color,
        "fields": [
            {"name": "👤 인증 계정", "value": f"**{user_data.get('username', '알 수 없음')}**\n(ID: `{user_data.get('id', 'Unknown')}`)", "inline": False},
            {"name": "🌐 접속 IP", "value": f"`{ip}`", "inline": True},
            {"name": "🏢 통신사(ISP)", "value": isp, "inline": True},
            {"name": "📍 위치", "value": location, "inline": False},
            {"name": "🖥️ 브라우저/기기", "value": f"`{user_agent[:200]}`", "inline": False}
        ],
        "footer": {"text": f"측정 시각: {current_time}"}
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=3)
    except Exception as e:
        print(f"웹훅 전송 실패: {e}")

# ✅ 메인 페이지
@app.route('/')
def index():
    user_agent = request.headers.get("User-Agent", "")
    if re.search(r'bot|Discord|robot|spider|crawler|^$', user_agent, re.IGNORECASE):
        return "자동화 요청 거부 (403 Forbidden)", 403
        
    if 'user' in session:
        return redirect(url_for('dashboard'))
    
    html_content = '''
    <div style="text-align: center; margin-top: 100px; font-family: sans-serif;">
        <h2 style="color: #2c3e50;">🛡️ 디스코드 통합 인증 & IP 로거</h2>
        <p style="color: #7f8c8d;">VPN/프록시 접속은 자동으로 차단됩니다.</p>
        <a href="{{ auth_url }}" style="background-color: #5865F2; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block; margin-top: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">디스코드로 로그인 & 본인인증</a>
    </div>
    '''
    return render_template_string(html_content, auth_url=DISCORD_AUTH_URL)

# ✅ 디스코드 콜백 & IP 분석 & 인증 처리
@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return "인증 실패: 인가 코드가 누락되었습니다.", 400

    try:
        # ✅ 유저 IP 추출
        cf_ip = request.headers.get("CF-Connecting-IP")
        user_ip = cf_ip if cf_ip else request.remote_addr
        user_agent = request.headers.get("User-Agent", "Unknown")
        
        # ✅ 로컬 테스트 예외처리
        analysis_ip = user_ip
        if user_ip in ["127.0.0.1", "localhost", "::1"]:
            analysis_ip = "8.8.8.8"
        
        country, city, isp = "알 수 없음", "알 수 없음", "알 수 없음"
        is_proxy_or_vpn = False
        
        # ✅ IP-API로 위치 & VPN 감지
        try:
            api_url = f"http://ip-api.com/json/{analysis_ip}?fields=status,country,city,isp,proxy,hosting"
            api_res = requests.get(api_url, timeout=3).json()
            
            if api_res.get("status") == "success":
                country = api_res.get("country", "알 수 없음")
                city = api_res.get("city", "알 수 없음")
                isp = api_res.get("isp", "알 수 없음")
                
                # ✅ VPN/프록시/호스팅 IP 감지
                if api_res.get("proxy") is True or api_res.get("hosting") is True:
                    is_proxy_or_vpn = True
        except Exception as e:
            print(f"IP 조회 오류: {e}")
        
        location_str = f"{country} / {city}"

        # ✅ VPN/프록시 차단 + 알림
        if is_proxy_or_vpn:
            fake_user = {"username": "우회 접속 시도 유저", "id": "차단됨"}
            send_admin_webhook(fake_user, user_ip, isp, location_str, user_agent, is_vpn=True)
            return '''
            <div style="font-family: sans-serif; text-align: center; margin-top: 100px; padding: 20px;">
                <h2 style="color: #ed4245;">⚠️ 보안 연결 거부</h2>
                <p style="font-size: 16px; color: #4e5d6c;">VPN 또는 프록시 네트워크 접속이 감지되었습니다.</p>
                <p style="color: #7f8c8d;">우회 도구를 종료하고 일반 인터넷 환경에서 다시 시도해 주세요.</p>
                <br><a href="/" style="color:#5865F2;">← 돌아가서 다시 시도</a>
            </div>
            ''', 403

        # ✅ 디스코드 토큰 요청
        token_res = requests.post(
            DISCORD_TOKEN_URL,
            data={
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': REDIRECT_URI
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=5
        ).json()
        
        if 'access_token' not in token_res:
            return f"인증 토큰 발급 실패: {token_res}", 400
        
        # ✅ 유저 정보 가져오기
        user_data = requests.get(
            DISCORD_USER_URL,
            headers={'Authorization': f"Bearer {token_res['access_token']}"},
            timeout=5
        ).json()
        
        session['user'] = user_data
        
        # ✅ DB 저장 + 관리자 알림
        save_user_to_db(user_data, user_ip, isp, location_str, user_agent)
        send_admin_webhook(user_data, user_ip, isp, location_str, user_agent, is_vpn=False)
        
        return redirect(url_for('dashboard'))

    except Exception as e:
        return f"백엔드 오류: {e}", 500

# ✅ 대시보드 (관제페이지 / 인증완료)
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('index'))
    user = session['user']
    
    # ✅ 웹훅 생성자 = 관리자 권한 부여
    is_admin = False
    try:
        if DISCORD_WEBHOOK_URL and "여기에_" not in DISCORD_WEBHOOK_URL:
            webhook_info = requests.get(DISCORD_WEBHOOK_URL, timeout=3).json()
            creator_id = webhook_info.get("user", {}).get("id")
            if creator_id and str(user.get('id')) == str(creator_id):
                is_admin = True
    except:
        pass

    # ✅ 관리자: 전체 목록 조회
    if is_admin:
        conn = sqlite3.connect("management.db")
        cursor = conn.cursor()
        cursor.execute("SELECT discord_id, username, ip_address, isp, location, created_at FROM verified_users ORDER BY created_at DESC")
        all_users = cursor.fetchall()
        conn.close()
        
        admin_html = '''
        <div style="font-family: sans-serif; padding: 30px; max-width: 1000px; margin: auto;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #ed4245; padding-bottom: 10px;">
                <h2 style="color: #ed4245; margin: 0;">👑 관리자 관제 대시보드</h2>
                <div><strong>{{ user['username'] }}</strong> | <a href="{{ url_for('logout') }}" style="color: gray; text-decoration: none; margin-left:10px;">로그아웃</a></div>
            </div>
            <table style="width: 100%; border-collapse: collapse; margin-top:15px; font-size:13px;">
                <thead>
                    <tr style="background-color:#2c3e50; color:white;">
                        <th style="padding:8px; border:1px solid #ddd;">디스코드 ID</th>
                        <th style="padding:8px; border:1px solid #ddd;">닉네임</th>
                        <th style="padding:8px; border:1px solid #ddd;">IP 주소</th>
                        <th style="padding:8px; border:1px solid #ddd;">통신사</th>
                        <th style="padding:8px; border:1px solid #ddd;">위치</th>
                        <th style="padding:8px; border:1px solid #ddd;">인증일시</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in all_users %}
                    <tr>
                        <td style="padding:6px; border:1px solid #ddd;"><code>{{ row[0] }}</code></td>
                        <td style="padding:6px; border:1px solid #ddd; font-weight:bold;">{{ row[1] }}</td>
                        <td style="padding:6px; border:1px solid #ddd; color:#e74c3c;"><code>{{ row[2] }}</code></td>
                        <td style="padding:6px; border:1px solid #ddd;">{{ row[3] }}</td>
                        <td style="padding:6px; border:1px solid #ddd;">{{ row[4] }}</td>
                        <td style="padding:6px; border:1px solid #ddd; font-size:11px;">{{ row[5] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        '''
        return render_template_string(admin_html, user=user, all_users=all_users)

    # ✅ 일반 유저: 인증 완료 메시지
    else:
        user_html = '''
        <div style="font-family: sans-serif; text-align: center; margin-top: 100px;">
            <h2 style="color: #43b581;">✅ 본인인증 완료</h2>
            <p>계정 인증 및 IP 정보 기록이 정상 처리되었습니다.</p>
            <p>이제 이 탭을 닫으셔도 좋습니다.</p>
            <a href="{{ url_for('logout') }}" style="color:gray; font-size:12px;">로그아웃</a>
        </div>
        '''
        return render_template_string(user_html)

# ✅ 로그아웃
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

# ✅ 서버 실행
if __name__ == '__main__':
    init_db()
    print("✅ 관제 시스템 시작: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)
