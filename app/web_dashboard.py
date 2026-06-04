import cv2
import subprocess
import os
from flask import Flask, jsonify, Response, request, redirect
from app import config

try:
    import app.network_manager as nm
    import app.bluetooth_manager as bm
    from app.event_logger import log_event, get_events, clear_events
except ImportError:
    nm = bm = None
    def log_event(c, m, l="info"): pass
    def get_events(limit=100, category=None): return []
    def clear_events(): pass

app = Flask(__name__)

# Very simple state representation for the dashboard
system_state = {
    "status": "running",
    "cameras_active": 0,
    "last_spoken_message": "None",
    "pothole_detections": 0,
    "pothole_model_loaded": False,
}

# Global variable to hold the latest frame
latest_frame = None

# ─── Shared CSS Design System ───────────────────────────────────────────────
SHARED_CSS = """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    :root {
        --bg-primary: #0a0a14;
        --bg-card: rgba(20, 20, 42, 0.85);
        --bg-card-hover: rgba(30, 30, 58, 0.95);
        --accent: #6c5ce7;
        --accent-light: #a29bfe;
        --accent-glow: rgba(108, 92, 231, 0.25);
        --success: #00cec9;
        --success-dim: rgba(0, 206, 201, 0.15);
        --danger: #ff6b6b;
        --danger-dim: rgba(255, 107, 107, 0.15);
        --warning: #feca57;
        --warning-dim: rgba(254, 202, 87, 0.15);
        --info: #74b9ff;
        --info-dim: rgba(116, 185, 255, 0.15);
        --text: #e8e8f0;
        --text-dim: #7878a0;
        --border: rgba(255, 255, 255, 0.06);
        --border-hover: rgba(108, 92, 231, 0.3);
        --radius: 14px;
        --shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
    }
    body {
        font-family: 'Inter', sans-serif;
        background: var(--bg-primary);
        color: var(--text);
        min-height: 100vh;
        overflow-x: hidden;
    }
    body::before {
        content: '';
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background: radial-gradient(ellipse at 20% 50%, rgba(108, 92, 231, 0.07) 0%, transparent 50%),
                    radial-gradient(ellipse at 80% 20%, rgba(0, 206, 201, 0.05) 0%, transparent 50%),
                    radial-gradient(ellipse at 50% 80%, rgba(255, 107, 107, 0.03) 0%, transparent 50%);
        z-index: -1;
        animation: bgPulse 10s ease-in-out infinite alternate;
    }
    @keyframes bgPulse { 0% { opacity: 0.5; } 100% { opacity: 1; } }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
    @keyframes spin { to { transform: rotate(360deg); } }

    .header {
        padding: 18px 28px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid var(--border);
        backdrop-filter: blur(20px);
        position: sticky;
        top: 0;
        z-index: 100;
        background: rgba(10, 10, 20, 0.9);
    }
    .header h1 {
        font-size: 1.3em;
        font-weight: 700;
        background: linear-gradient(135deg, #6c5ce7, #00cec9);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .nav-links { display: flex; gap: 10px; align-items: center; }
    .nav-links a {
        color: var(--text-dim);
        text-decoration: none;
        padding: 7px 14px;
        border-radius: 8px;
        font-size: 0.82em;
        font-weight: 500;
        transition: all 0.25s;
        border: 1px solid transparent;
    }
    .nav-links a:hover, .nav-links a.active {
        color: var(--text);
        background: rgba(108, 92, 231, 0.12);
        border-color: var(--border-hover);
    }
    .card {
        background: var(--bg-card);
        border-radius: var(--radius);
        border: 1px solid var(--border);
        backdrop-filter: blur(12px);
        transition: all 0.3s;
        overflow: hidden;
        box-shadow: var(--shadow);
        animation: fadeIn 0.4s ease;
    }
    .card:hover { border-color: var(--border-hover); }
    .card-header {
        padding: 14px 18px;
        border-bottom: 1px solid var(--border);
        font-weight: 600;
        font-size: 0.85em;
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--text-dim);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .btn {
        background: var(--accent);
        color: white;
        border: none;
        padding: 9px 18px;
        border-radius: 8px;
        cursor: pointer;
        font-family: 'Inter';
        font-weight: 600;
        font-size: 0.85em;
        transition: all 0.25s;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .btn:hover { background: #5a4bcf; transform: translateY(-1px); }
    .btn:active { transform: translateY(0); }
    .btn-success { background: var(--success); }
    .btn-success:hover { background: #00b5b1; }
    .btn-danger { background: var(--danger); }
    .btn-danger:hover { background: #e55a5a; }
    .btn-sm { padding: 5px 12px; font-size: 0.8em; }
    input[type="password"], input[type="text"] {
        background: rgba(0,0,0,0.3);
        border: 1px solid rgba(255,255,255,0.15);
        color: white;
        padding: 8px 12px;
        border-radius: 8px;
        font-family: 'Inter';
        font-size: 0.85em;
        outline: none;
        transition: border-color 0.2s;
    }
    input:focus { border-color: var(--accent); }
    .spinner {
        width: 22px; height: 22px;
        border: 3px solid var(--border);
        border-top-color: var(--accent);
        border-radius: 50%;
        animation: spin 0.7s linear infinite;
        display: inline-block;
        vertical-align: middle;
        margin-left: 8px;
    }
    .badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.78em;
        font-weight: 500;
    }
    .badge-success { background: var(--success-dim); color: var(--success); }
    .badge-danger { background: var(--danger-dim); color: var(--danger); }
    .badge-warning { background: var(--warning-dim); color: var(--warning); }
    .badge-info { background: var(--info-dim); color: var(--info); }
    .footer {
        text-align: center;
        padding: 20px;
        color: var(--text-dim);
        font-size: 0.72em;
    }
    @media (max-width: 900px) {
        .header { padding: 14px 16px; }
        .nav-links a { padding: 6px 10px; font-size: 0.75em; }
    }
"""

NAV_HTML = """
    <div class="header">
        <h1>🔬 Vision + Voice AI</h1>
        <div class="nav-links">
            <a href="/" id="nav-home">📹 المراقبة</a>
            <a href="/setup" id="nav-setup">⚙️ الاتصال</a>
            <a href="/sysinfo" id="nav-sysinfo">🖥️ النظام</a>
            <a href="/events" id="nav-events">📋 السجل</a>
        </div>
    </div>
"""

def generate_frames():
    global latest_frame
    while True:
        if latest_frame is None:
            continue
        ret, buffer = cv2.imencode('.jpg', latest_frame)
        if not ret:
            continue
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE: Main Dashboard
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Vision AI - لوحة المراقبة</title>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
            <style>
                {SHARED_CSS}
                .container {{
                    max-width: 1400px;
                    margin: 0 auto;
                    padding: 24px;
                    display: grid;
                    grid-template-columns: 1fr 340px;
                    gap: 20px;
                }}
                .video-card img {{
                    width: 100%;
                    display: block;
                    border-radius: 0 0 var(--radius) var(--radius);
                }}
                .sidebar {{
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                }}
                .stat-card {{ padding: 18px; }}
                .stat-card .stat-value {{
                    font-size: 2em;
                    font-weight: 700;
                    margin: 6px 0 4px;
                }}
                .stat-card .stat-label {{
                    font-size: 0.78em;
                    color: var(--text-dim);
                }}
                .stat-card.pothole .stat-value {{ color: var(--danger); }}
                .model-status {{
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    padding: 6px 14px;
                    border-radius: 8px;
                    font-size: 0.85em;
                    font-weight: 500;
                }}
                .model-status.loaded {{ background: var(--success-dim); color: var(--success); }}
                .model-status.not-loaded {{ background: var(--danger-dim); color: var(--danger); }}
                .info-row {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 10px 0;
                    border-bottom: 1px solid var(--border);
                    font-size: 0.88em;
                }}
                .info-row:last-child {{ border-bottom: none; }}
                .info-row .label {{ color: var(--text-dim); }}
                .info-row .value {{ font-weight: 600; }}
                .conn-widget {{ padding: 16px; }}
                .conn-row {{ display: flex; justify-content: space-between; align-items: center; padding: 8px 0; font-size: 0.85em; }}
                .dot-live {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; animation: pulse 2s infinite; }}
                @keyframes pulse {{
                    0%, 100% {{ opacity: 1; box-shadow: 0 0 0 0 rgba(0,206,201,0.5); }}
                    50% {{ opacity: 0.7; box-shadow: 0 0 0 6px rgba(0,206,201,0); }}
                }}
                @media (max-width: 900px) {{
                    .container {{ grid-template-columns: 1fr; }}
                }}
            </style>
        </head>
        <body>
            {NAV_HTML}
            <script>document.getElementById('nav-home').classList.add('active');</script>

            <div class="container">
                <div class="card video-card">
                    <div class="card-header">📹 البث المباشر - الكاميرا</div>
                    <img src="/video_feed" alt="Live Camera Feed">
                </div>

                <div class="sidebar">
                    <!-- Connection Status Widget -->
                    <div class="card conn-widget">
                        <div class="card-header">🌐 حالة الاتصال</div>
                        <div class="conn-row">
                            <span style="color:var(--text-dim)">الإنترنت</span>
                            <span id="conn-internet" class="badge badge-info">...</span>
                        </div>
                        <div class="conn-row">
                            <span style="color:var(--text-dim)">الشبكة</span>
                            <span id="conn-ssid" style="font-weight:600">—</span>
                        </div>
                        <div class="conn-row">
                            <span style="color:var(--text-dim)">IP</span>
                            <span id="conn-ip" style="font-weight:600; font-size:0.85em; direction:ltr">—</span>
                        </div>
                        <div class="conn-row">
                            <span style="color:var(--text-dim)">Hotspot</span>
                            <span id="conn-hotspot" class="badge badge-info">...</span>
                        </div>
                    </div>

                    <div class="card stat-card">
                        <div class="card-header">🤖 موديل الحفر</div>
                        <div style="padding: 4px 0;">
                            <span class="model-status" id="ph-model-badge">⏳ جاري التحميل...</span>
                        </div>
                    </div>


                    <div class="card" style="padding:18px;">
                        <div class="card-header" style="padding:0 0 12px; border:none;">⚙️ معلومات النظام</div>
                     
                        <div class="info-row">
                            <span class="label">حساسية التصادم</span>
                            <span class="value">Force 1</span>
                        </div>
                        <div class="info-row">
                            <span class="label">تنبيه الحفر</span>
                            <span class="value">🔔 متقطع</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="footer">Vision + Voice AI Assistant &copy; 2026 — Jetson Orin Nano</div>

            <script>
                function updateDashboard() {{
                    fetch('/api/status').then(r => r.json()).then(data => {{
                        document.getElementById('ph-count').innerText = data.pothole_detections;
                        const modelBadge = document.getElementById('ph-model-badge');
                        if (data.pothole_model_loaded) {{
                            modelBadge.className = 'model-status loaded';
                            modelBadge.innerHTML = '✅ محمّل وجاهز';
                        }} else {{
                            modelBadge.className = 'model-status not-loaded';
                            modelBadge.innerHTML = '❌ غير محمّل';
                        }}
                        document.getElementById('cam-count').innerText = data.cameras_active || 0;
                    }}).catch(() => {{}});

                    fetch('/api/connection').then(r => r.json()).then(c => {{
                        document.getElementById('conn-internet').className = 'badge ' + (c.internet ? 'badge-success' : 'badge-danger');
                        document.getElementById('conn-internet').innerHTML = c.internet ? '<span class="dot-live" style="background:var(--success)"></span> متصل' : '❌ غير متصل';
                        document.getElementById('conn-ssid').innerText = c.current_ssid || '—';
                        document.getElementById('conn-ip').innerText = c.ip_address || '—';
                        document.getElementById('conn-hotspot').className = 'badge ' + (c.hotspot_active ? 'badge-warning' : 'badge-info');
                        document.getElementById('conn-hotspot').innerText = c.hotspot_active ? '📡 شغال' : '⏸️ متوقف';
                    }}).catch(() => {{}});
                }}
                updateDashboard();
                setInterval(updateDashboard, 4000);
            </script>
        </body>
    </html>
    """
    return html

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE: Setup Page (Wi-Fi + Bluetooth)
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/setup")
def setup_page():
    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>إعدادات الاتصال</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            {SHARED_CSS}
            .page-content {{ max-width: 800px; margin: 0 auto; padding: 24px; }}
            .section-title {{ font-size: 1.1em; font-weight: 600; margin: 24px 0 12px; color: var(--accent-light); }}
            .list-item {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 14px 16px;
                border-bottom: 1px solid var(--border);
                transition: background 0.2s;
            }}
            .list-item:hover {{ background: rgba(255,255,255,0.02); }}
            .list-item:last-child {{ border-bottom: none; }}
            .signal-bar {{ display: inline-block; width: 40px; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; margin-left: 8px; }}
            .signal-bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.3s; }}
            .current-net {{ padding: 16px; margin-bottom: 16px; border-radius: var(--radius); background: var(--success-dim); border: 1px solid rgba(0,206,201,0.2); }}
            .empty-state {{ text-align: center; padding: 30px; color: var(--text-dim); font-size: 0.9em; }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <script>document.getElementById('nav-setup').classList.add('active');</script>

        <div class="page-content">
            <div id="current-net-box"></div>

            <div class="card" style="margin-bottom:20px;">
                <div class="card-header">📶 شبكات Wi-Fi المتاحة</div>
                <div style="padding:14px;">
                    <button class="btn" onclick="scanWifi()" id="wifi-scan-btn">🔍 بحث عن شبكات</button>
                </div>
                <div id="wifi-list"><div class="empty-state">اضغط "بحث" لعرض الشبكات</div></div>
            </div>

            <div class="card">
                <div class="card-header">🎧 أجهزة البلوتوث</div>
                <div style="padding:14px;">
                    <button class="btn" onclick="scanBt()" id="bt-scan-btn">🔍 بحث عن أجهزة</button>
                </div>
                <div id="bt-list"><div class="empty-state">اضغط "بحث" لعرض الأجهزة</div></div>
            </div>
        </div>

        <div class="footer">Vision + Voice AI Assistant &copy; 2026</div>

        <script>
            // Load current network status on page load
            fetch('/api/connection').then(r => r.json()).then(c => {{
                const box = document.getElementById('current-net-box');
                if (c.current_ssid) {{
                    box.innerHTML = `<div class="current-net">
                        <strong>✅ متصل بـ: ${{c.current_ssid}}</strong>
                        <span style="margin-right:16px; color:var(--text-dim); font-size:0.85em">IP: ${{c.ip_address}}</span>
                        ${{c.hotspot_active ? '<span class="badge badge-warning" style="margin-right:8px">📡 Hotspot شغال</span>' : ''}}
                    </div>`;
                }} else if (c.hotspot_active) {{
                    box.innerHTML = '<div class="current-net" style="background:var(--warning-dim);border-color:rgba(254,202,87,0.3)"><strong>📡 وضع نقطة الاتصال (Jetson-Setup)</strong></div>';
                }}
            }});

            function scanWifi() {{
                const list = document.getElementById('wifi-list');
                const btn = document.getElementById('wifi-scan-btn');
                btn.disabled = true;
                btn.innerHTML = '🔍 جاري البحث... <span class="spinner"></span>';
                list.innerHTML = '';

                fetch('/api/wifi/scan').then(r => r.json()).then(data => {{
                    btn.disabled = false;
                    btn.innerHTML = '🔍 بحث عن شبكات';
                    if (data.length === 0) {{ list.innerHTML = '<div class="empty-state">لا يوجد شبكات متاحة</div>'; return; }}
                    data.forEach(net => {{
                        const sig = parseInt(net.signal) || 0;
                        const sigColor = sig > 70 ? 'var(--success)' : sig > 40 ? 'var(--warning)' : 'var(--danger)';
                        list.innerHTML += `
                            <div class="list-item">
                                <div>
                                    <strong>${{net.ssid}}</strong>
                                    <span class="signal-bar"><span class="signal-bar-fill" style="width:${{sig}}%; background:${{sigColor}}"></span></span>
                                    <small style="color:var(--text-dim)">${{sig}}%</small>
                                    ${{net.security !== 'Open' ? '<span class="badge badge-info" style="margin-right:6px">🔒</span>' : '<span class="badge badge-success" style="margin-right:6px">مفتوحة</span>'}}
                                </div>
                                <div style="display:flex; align-items:center; gap:8px">
                                    ${{net.security !== 'Open' ? '<input type="password" id="pass-' + net.ssid + '" placeholder="كلمة السر">' : ''}}
                                    <button class="btn btn-success btn-sm" onclick="connectWifi('${{net.ssid}}', ${{net.security !== 'Open'}})">اتصال</button>
                                </div>
                            </div>
                        `;
                    }});
                }});
            }}

            function connectWifi(ssid, hasPass) {{
                const pass = hasPass ? document.getElementById('pass-' + ssid)?.value : null;
                if (hasPass && !pass) {{ alert('يرجى إدخال كلمة السر'); return; }}
                if (!confirm('هل تريد الاتصال بشبكة ' + ssid + '؟\\nملاحظة: قد ينقطع اتصالك الحالي.')) return;
                fetch('/api/wifi/connect', {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ssid: ssid, password: pass}})
                }}).then(r => r.json()).then(data => {{
                    alert(data.message);
                    if (data.success) location.reload();
                }});
            }}

            function scanBt() {{
                const list = document.getElementById('bt-list');
                const btn = document.getElementById('bt-scan-btn');
                btn.disabled = true;
                btn.innerHTML = '🔍 جاري البحث... <span class="spinner"></span>';
                list.innerHTML = '';

                fetch('/api/bt/scan').then(r => r.json()).then(data => {{
                    btn.disabled = false;
                    btn.innerHTML = '🔍 بحث عن أجهزة';
                    if (data.length === 0) {{ list.innerHTML = '<div class="empty-state">لا يوجد أجهزة بلوتوث</div>'; return; }}
                    data.forEach(dev => {{
                        list.innerHTML += `
                            <div class="list-item">
                                <div>
                                    <strong>${{dev.name}}</strong>
                                    <small style="color:var(--text-dim); direction:ltr; display:inline-block">${{dev.mac}}</small><br>
                                    <span class="badge ${{dev.connected ? 'badge-success' : (dev.paired ? 'badge-warning' : 'badge-info')}}" style="margin-top:4px">
                                        ${{dev.connected ? '✅ متصل' : (dev.paired ? '🔗 مقترن' : '📡 متاح')}}
                                    </span>
                                </div>
                                <div style="display:flex; gap:6px">
                                    ${{dev.connected
                                        ? '<button class="btn btn-danger btn-sm" onclick="disconnectBt(\\'' + dev.mac + '\\')">فصل</button>'
                                        : '<button class="btn btn-success btn-sm" onclick="connectBt(\\'' + dev.mac + '\\')">اقتران</button>'
                                    }}
                                </div>
                            </div>
                        `;
                    }});
                }});
            }}

            function connectBt(mac) {{
                fetch('/api/bt/connect', {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{mac: mac}})
                }}).then(r => r.json()).then(data => {{
                    alert(data.message);
                    scanBt();
                }});
            }}

            function disconnectBt(mac) {{
                fetch('/api/bt/disconnect', {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{mac: mac}})
                }}).then(r => r.json()).then(data => {{
                    alert(data.message);
                    scanBt();
                }});
            }}
        </script>
    </body>
    </html>
    """
    return html

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE: System Info
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/sysinfo")
def sysinfo_page():
    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>معلومات النظام</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            {SHARED_CSS}
            .page-content {{ max-width: 900px; margin: 0 auto; padding: 24px; }}
            .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
            .metric {{ padding: 20px; }}
            .metric .metric-value {{ font-size: 1.8em; font-weight: 700; margin: 8px 0 2px; }}
            .metric .metric-label {{ font-size: 0.78em; color: var(--text-dim); }}
            .progress-bar {{ width: 100%; height: 8px; background: var(--border); border-radius: 4px; margin-top: 8px; overflow: hidden; }}
            .progress-fill {{ height: 100%; border-radius: 4px; transition: width 0.5s; }}
            @media (max-width: 600px) {{ .grid {{ grid-template-columns: 1fr; }} }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <script>document.getElementById('nav-sysinfo').classList.add('active');</script>

        <div class="page-content">
            <div class="grid">
                <div class="card metric">
                    <div class="card-header">🌡️ درجة الحرارة</div>
                    <div class="metric-value" id="temp">—</div>
                    <div class="metric-label">°C</div>
                    <div class="progress-bar"><div class="progress-fill" id="temp-bar" style="width:0%;background:var(--success)"></div></div>
                </div>
                <div class="card metric">
                    <div class="card-header">🧠 الذاكرة (RAM)</div>
                    <div class="metric-value" id="ram">—</div>
                    <div class="metric-label" id="ram-detail">—</div>
                    <div class="progress-bar"><div class="progress-fill" id="ram-bar" style="width:0%;background:var(--info)"></div></div>
                </div>
                <div class="card metric">
                    <div class="card-header">💾 التخزين</div>
                    <div class="metric-value" id="disk">—</div>
                    <div class="metric-label" id="disk-detail">—</div>
                    <div class="progress-bar"><div class="progress-fill" id="disk-bar" style="width:0%;background:var(--accent)"></div></div>
                </div>
                <div class="card metric">
                    <div class="card-header">⚡ CPU</div>
                    <div class="metric-value" id="cpu">—</div>
                    <div class="metric-label">% استخدام</div>
                    <div class="progress-bar"><div class="progress-fill" id="cpu-bar" style="width:0%;background:var(--warning)"></div></div>
                </div>
            </div>

            <div class="card" style="padding:20px; margin-bottom:20px;">
                <div class="card-header" style="padding:0 0 12px; border:none;">⏱️ وقت التشغيل</div>
                <div id="uptime" style="font-size:1.1em; font-weight:600;">—</div>
            </div>

            <div class="card" style="padding:20px;">
                <div class="card-header" style="padding:0 0 12px; border:none;">🔄 تحديث النظام (OTA)</div>
                <p style="color:var(--text-dim); font-size:0.85em; margin-bottom:12px;">سحب آخر تحديث من GitHub وإعادة تشغيل النظام.</p>
                <button class="btn" onclick="otaUpdate()" id="ota-btn">🔄 تحديث الآن</button>
                <pre id="ota-output" style="margin-top:12px; background:rgba(0,0,0,0.3); padding:12px; border-radius:8px; font-size:0.8em; max-height:200px; overflow-y:auto; display:none; direction:ltr; text-align:left;"></pre>
            </div>
        </div>

        <div class="footer">Vision + Voice AI Assistant &copy; 2026</div>

        <script>
            function getColor(pct) {{
                if (pct > 85) return 'var(--danger)';
                if (pct > 60) return 'var(--warning)';
                return 'var(--success)';
            }}

            function updateSysinfo() {{
                fetch('/api/sysinfo').then(r => r.json()).then(d => {{
                    document.getElementById('temp').innerText = d.temperature;
                    const tempPct = Math.min(100, (parseFloat(d.temperature) / 90) * 100);
                    document.getElementById('temp-bar').style.width = tempPct + '%';
                    document.getElementById('temp-bar').style.background = getColor(tempPct);

                    document.getElementById('ram').innerText = d.ram_percent + '%';
                    document.getElementById('ram-detail').innerText = d.ram_used + ' / ' + d.ram_total;
                    document.getElementById('ram-bar').style.width = d.ram_percent + '%';
                    document.getElementById('ram-bar').style.background = getColor(parseFloat(d.ram_percent));

                    document.getElementById('disk').innerText = d.disk_percent + '%';
                    document.getElementById('disk-detail').innerText = d.disk_used + ' / ' + d.disk_total;
                    document.getElementById('disk-bar').style.width = d.disk_percent + '%';
                    document.getElementById('disk-bar').style.background = getColor(parseFloat(d.disk_percent));

                    document.getElementById('cpu').innerText = d.cpu_percent;
                    document.getElementById('cpu-bar').style.width = d.cpu_percent + '%';
                    document.getElementById('cpu-bar').style.background = getColor(parseFloat(d.cpu_percent));

                    document.getElementById('uptime').innerText = d.uptime;
                }}).catch(() => {{}});
            }}
            updateSysinfo();
            setInterval(updateSysinfo, 5000);

            function otaUpdate() {{
                if (!confirm('هل تريد تحديث النظام من GitHub؟')) return;
                const btn = document.getElementById('ota-btn');
                const out = document.getElementById('ota-output');
                btn.disabled = true;
                btn.innerHTML = '⏳ جاري التحديث... <span class="spinner"></span>';
                out.style.display = 'block';
                out.innerText = 'جاري سحب التحديثات...\\n';

                fetch('/api/ota/update', {{ method: 'POST' }}).then(r => r.json()).then(data => {{
                    btn.disabled = false;
                    btn.innerHTML = '🔄 تحديث الآن';
                    out.innerText += data.output;
                    if (data.success) {{
                        out.innerText += '\\n✅ تم التحديث بنجاح!';
                    }} else {{
                        out.innerText += '\\n❌ فشل التحديث.';
                    }}
                }}).catch(e => {{
                    btn.disabled = false;
                    btn.innerHTML = '🔄 تحديث الآن';
                    out.innerText += '\\n❌ خطأ في الاتصال.';
                }});
            }}
        </script>
    </body>
    </html>
    """
    return html

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE: Event Log
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/events")
def events_page():
    html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>سجل الأحداث</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            {SHARED_CSS}
            .page-content {{ max-width: 900px; margin: 0 auto; padding: 24px; }}
            .toolbar {{ display: flex; gap: 8px; padding: 14px; flex-wrap: wrap; align-items: center; }}
            .filter-btn {{
                padding: 5px 14px;
                border-radius: 20px;
                border: 1px solid var(--border);
                background: transparent;
                color: var(--text-dim);
                cursor: pointer;
                font-family: 'Inter';
                font-size: 0.8em;
                transition: all 0.2s;
            }}
            .filter-btn:hover, .filter-btn.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
            .event-item {{
                display: flex;
                gap: 14px;
                padding: 12px 16px;
                border-bottom: 1px solid var(--border);
                font-size: 0.88em;
                animation: fadeIn 0.3s ease;
            }}
            .event-item:hover {{ background: rgba(255,255,255,0.02); }}
            .event-time {{ color: var(--text-dim); font-size: 0.82em; white-space: nowrap; direction: ltr; min-width: 65px; }}
            .event-cat {{
                font-size: 0.72em;
                padding: 2px 8px;
                border-radius: 4px;
                font-weight: 600;
                text-transform: uppercase;
                white-space: nowrap;
            }}
            .cat-network {{ background: var(--info-dim); color: var(--info); }}
            .cat-bluetooth {{ background: var(--accent-glow); color: var(--accent-light); }}
            .cat-detection {{ background: var(--danger-dim); color: var(--danger); }}
            .cat-system {{ background: var(--warning-dim); color: var(--warning); }}
            .cat-ota {{ background: var(--success-dim); color: var(--success); }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <script>document.getElementById('nav-events').classList.add('active');</script>

        <div class="page-content">
            <div class="card">
                <div class="card-header" style="justify-content:space-between;">
                    📋 سجل الأحداث
                    <button class="btn btn-danger btn-sm" onclick="clearLog()">🗑️ مسح</button>
                </div>
                <div class="toolbar">
                    <button class="filter-btn active" onclick="filterEvents(this, '')">الكل</button>
                    <button class="filter-btn" onclick="filterEvents(this, 'network')">🌐 الشبكة</button>
                    <button class="filter-btn" onclick="filterEvents(this, 'bluetooth')">🎧 بلوتوث</button>
                    <button class="filter-btn" onclick="filterEvents(this, 'detection')">🔍 كشف</button>
                    <button class="filter-btn" onclick="filterEvents(this, 'system')">⚙️ النظام</button>
                    <button class="filter-btn" onclick="filterEvents(this, 'ota')">🔄 تحديث</button>
                </div>
                <div id="events-list"></div>
            </div>
        </div>

        <div class="footer">Vision + Voice AI Assistant &copy; 2026</div>

        <script>
            let currentFilter = '';

            function loadEvents() {{
                let url = '/api/events';
                if (currentFilter) url += '?category=' + currentFilter;
                fetch(url).then(r => r.json()).then(events => {{
                    const list = document.getElementById('events-list');
                    if (events.length === 0) {{
                        list.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-dim)">لا توجد أحداث</div>';
                        return;
                    }}
                    list.innerHTML = events.map(e => `
                        <div class="event-item">
                            <span class="event-time">${{e.timestamp.split(' ')[1] || e.timestamp}}</span>
                            <span class="event-cat cat-${{e.category}}">${{e.category}}</span>
                            <span class="badge badge-${{e.level === 'error' ? 'danger' : e.level === 'warning' ? 'warning' : e.level === 'success' ? 'success' : 'info'}}" style="font-size:0.7em">${{e.level}}</span>
                            <span>${{e.message}}</span>
                        </div>
                    `).join('');
                }});
            }}

            function filterEvents(btn, category) {{
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentFilter = category;
                loadEvents();
            }}

            function clearLog() {{
                if (!confirm('هل تريد مسح جميع الأحداث؟')) return;
                fetch('/api/events/clear', {{ method: 'POST' }}).then(() => loadEvents());
            }}

            loadEvents();
            setInterval(loadEvents, 5000);
        </script>
    </body>
    </html>
    """
    return html

# ═══════════════════════════════════════════════════════════════════════════════
# API Routes
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/status")
def api_status():
    return jsonify(system_state)

@app.route("/api/connection")
def api_connection():
    if nm:
        return jsonify(nm.connection_state)
    return jsonify({"internet": False, "hotspot_active": False, "current_ssid": "", "ip_address": ""})

@app.route("/api/wifi/scan")
def api_wifi_scan():
    return jsonify(nm.scan_wifi() if nm else [])

@app.route("/api/wifi/connect", methods=["POST"])
def api_wifi_connect():
    data = request.json
    return jsonify(nm.connect_wifi(data.get("ssid"), data.get("password")) if nm else {"success": False})

@app.route("/api/bt/scan")
def api_bt_scan():
    return jsonify(bm.scan_devices() if bm else [])

@app.route("/api/bt/connect", methods=["POST"])
def api_bt_connect():
    data = request.json
    return jsonify(bm.pair_and_connect(data.get("mac")) if bm else {"success": False})

@app.route("/api/bt/disconnect", methods=["POST"])
def api_bt_disconnect():
    data = request.json
    return jsonify(bm.disconnect_device(data.get("mac")) if bm else {"success": False})

@app.route("/api/sysinfo")
def api_sysinfo():
    info = {}
    
    # Temperature
    try:
        temp_output = subprocess.check_output(["cat", "/sys/devices/virtual/thermal/thermal_zone0/temp"], text=True).strip()
        info["temperature"] = f"{int(temp_output) / 1000:.1f}"
    except Exception:
        info["temperature"] = "N/A"
    
    # RAM
    try:
        mem = subprocess.check_output(["free", "-m"], text=True)
        lines = mem.strip().split('\n')
        parts = lines[1].split()
        total = int(parts[1])
        used = int(parts[2])
        info["ram_total"] = f"{total} MB"
        info["ram_used"] = f"{used} MB"
        info["ram_percent"] = f"{(used / total * 100):.0f}" if total > 0 else "0"
    except Exception:
        info["ram_total"] = info["ram_used"] = info["ram_percent"] = "N/A"
    
    # Disk
    try:
        disk = subprocess.check_output(["df", "-h", "/"], text=True)
        parts = disk.strip().split('\n')[1].split()
        info["disk_total"] = parts[1]
        info["disk_used"] = parts[2]
        info["disk_percent"] = parts[4].replace('%', '')
    except Exception:
        info["disk_total"] = info["disk_used"] = info["disk_percent"] = "N/A"
    
    # CPU
    try:
        cpu = subprocess.check_output(["grep", "cpu ", "/proc/stat"], text=True).split()
        idle = int(cpu[4])
        total_cpu = sum(int(x) for x in cpu[1:])
        info["cpu_percent"] = f"{100 - (idle / total_cpu * 100):.0f}" if total_cpu > 0 else "0"
    except Exception:
        info["cpu_percent"] = "N/A"
    
    # Uptime
    try:
        uptime_str = subprocess.check_output(["uptime", "-p"], text=True).strip()
        info["uptime"] = uptime_str.replace("up ", "")
    except Exception:
        info["uptime"] = "N/A"
    
    return jsonify(info)

@app.route("/api/ota/update", methods=["POST"])
def api_ota_update():
    try:
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            ["git", "pull"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout + result.stderr
        success = result.returncode == 0
        
        log_event("ota", f"تحديث OTA: {'نجح' if success else 'فشل'}", "success" if success else "error")
        
        return jsonify({"success": success, "output": output})
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "output": "انتهت المهلة الزمنية (60 ثانية)"})
    except Exception as e:
        return jsonify({"success": False, "output": str(e)})

@app.route("/api/events")
def api_events():
    category = request.args.get("category", None)
    return jsonify(get_events(limit=200, category=category if category else None))

@app.route("/api/events/clear", methods=["POST"])
def api_events_clear():
    clear_events()
    return jsonify({"success": True})

# Captive Portal: Redirect any 404 to /setup
@app.errorhandler(404)
def page_not_found(e):
    return redirect("/setup")

def run_server():
    app.run(host="0.0.0.0", port=config.WEB_PORT, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_server()
