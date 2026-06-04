import cv2
from flask import Flask, jsonify, Response, request, redirect
from app import config
try:
    import app.network_manager as nm
    import app.bluetooth_manager as bm
except ImportError:
    nm = bm = None

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

def generate_frames():
    global latest_frame
    while True:
        if latest_frame is None:
            continue
        
        # Encode the frame in JPEG format
        ret, buffer = cv2.imencode('.jpg', latest_frame)
        if not ret:
            continue
            
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route("/")
def index():
    html = """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Vision AI - لوحة المراقبة</title>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                :root {
                    --bg-primary: #0f0f1a;
                    --bg-card: rgba(25, 25, 50, 0.8);
                    --bg-card-hover: rgba(35, 35, 65, 0.9);
                    --accent: #6c5ce7;
                    --accent-glow: rgba(108, 92, 231, 0.3);
                    --success: #00cec9;
                    --danger: #ff6b6b;
                    --warning: #feca57;
                    --text: #e0e0e0;
                    --text-dim: #8888aa;
                    --border: rgba(255, 255, 255, 0.06);
                }
                body {
                    font-family: 'Inter', sans-serif;
                    background: var(--bg-primary);
                    color: var(--text);
                    min-height: 100vh;
                    overflow-x: hidden;
                }
                /* Animated background gradient */
                body::before {
                    content: '';
                    position: fixed;
                    top: 0; left: 0; right: 0; bottom: 0;
                    background: radial-gradient(ellipse at 20% 50%, rgba(108, 92, 231, 0.08) 0%, transparent 50%),
                                radial-gradient(ellipse at 80% 20%, rgba(0, 206, 201, 0.06) 0%, transparent 50%),
                                radial-gradient(ellipse at 50% 80%, rgba(255, 107, 107, 0.04) 0%, transparent 50%);
                    z-index: -1;
                    animation: bgPulse 8s ease-in-out infinite alternate;
                }
                @keyframes bgPulse {
                    0% { opacity: 0.6; }
                    100% { opacity: 1; }
                }
                .header {
                    padding: 24px 32px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    border-bottom: 1px solid var(--border);
                    backdrop-filter: blur(20px);
                    position: sticky;
                    top: 0;
                    z-index: 100;
                    background: rgba(15, 15, 26, 0.85);
                }
                .header h1 {
                    font-size: 1.4em;
                    font-weight: 700;
                    background: linear-gradient(135deg, #6c5ce7, #00cec9);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                }
                .status-badge {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 8px 16px;
                    border-radius: 20px;
                    font-size: 0.85em;
                    font-weight: 500;
                }
                .status-badge.online {
                    background: rgba(0, 206, 201, 0.15);
                    color: var(--success);
                    border: 1px solid rgba(0, 206, 201, 0.3);
                }
                .status-badge .dot {
                    width: 8px; height: 8px;
                    border-radius: 50%;
                    background: var(--success);
                    animation: pulse 2s infinite;
                }
                @keyframes pulse {
                    0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(0, 206, 201, 0.5); }
                    50% { opacity: 0.7; box-shadow: 0 0 0 6px rgba(0, 206, 201, 0); }
                }
                .container {
                    max-width: 1400px;
                    margin: 0 auto;
                    padding: 24px;
                    display: grid;
                    grid-template-columns: 1fr 340px;
                    gap: 24px;
                }
                .card {
                    background: var(--bg-card);
                    border-radius: 16px;
                    border: 1px solid var(--border);
                    backdrop-filter: blur(12px);
                    transition: transform 0.2s, border-color 0.3s;
                    overflow: hidden;
                }
                .card:hover {
                    border-color: rgba(108, 92, 231, 0.2);
                }
                .card-header {
                    padding: 16px 20px;
                    border-bottom: 1px solid var(--border);
                    font-weight: 600;
                    font-size: 0.9em;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    color: var(--text-dim);
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                .video-card {
                    grid-column: 1;
                }
                .video-card img {
                    width: 100%;
                    display: block;
                    border-radius: 0 0 16px 16px;
                }
                .sidebar {
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                }
                .stat-card {
                    padding: 20px;
                }
                .stat-card .stat-value {
                    font-size: 2em;
                    font-weight: 700;
                    margin: 8px 0 4px;
                }
                .stat-card .stat-label {
                    font-size: 0.8em;
                    color: var(--text-dim);
                }
                .stat-card.pothole .stat-value {
                    color: var(--danger);
                }
                .stat-card.model .stat-value {
                    font-size: 1em;
                }
                .model-status {
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    padding: 6px 14px;
                    border-radius: 8px;
                    font-size: 0.85em;
                    font-weight: 500;
                }
                .model-status.loaded {
                    background: rgba(0, 206, 201, 0.12);
                    color: var(--success);
                }
                .model-status.not-loaded {
                    background: rgba(255, 107, 107, 0.12);
                    color: var(--danger);
                }
                .info-row {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 12px 0;
                    border-bottom: 1px solid var(--border);
                    font-size: 0.9em;
                }
                .info-row:last-child { border-bottom: none; }
                .info-row .label { color: var(--text-dim); }
                .info-row .value { font-weight: 600; }
                .footer {
                    text-align: center;
                    padding: 24px;
                    color: var(--text-dim);
                    font-size: 0.75em;
                }
                @media (max-width: 900px) {
                    .container {
                        grid-template-columns: 1fr;
                    }
                }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🔬 Vision + Voice AI</h1>
                <div style="display:flex; gap: 15px; align-items:center;">
                    <a href="/setup" style="color:var(--text); text-decoration:none; background:rgba(255,255,255,0.1); padding:8px 16px; border-radius:8px; font-size:0.9em; transition: 0.2s;">⚙️ الإعدادات</a>
                    <div class="status-badge online" id="status-badge">
                        <span class="dot"></span>
                        <span id="sys-status">يعمل</span>
                    </div>
                </div>
            </div>

            <div class="container">
                <!-- Live Video Feed -->
                <div class="card video-card">
                    <div class="card-header">📹 البث المباشر - الكاميرا</div>
                    <img src="/video_feed" alt="Live Camera Feed">
                </div>

                <!-- Sidebar Stats -->
                <div class="sidebar">
                    <!-- Pothole Model Status -->
                    <div class="card stat-card model">
                        <div class="card-header">🤖 موديل الحفر</div>
                        <div style="padding: 4px 0;">
                            <span class="model-status" id="ph-model-badge">
                                ⏳ جاري التحميل...
                            </span>
                        </div>
                        <div class="stat-label" style="margin-top:8px;">pothole-vhmow/2</div>
                    </div>

                    <!-- Pothole Count -->
                    <div class="card stat-card pothole">
                        <div class="card-header">🕳️ الحفر المكتشفة</div>
                        <div class="stat-value" id="ph-count">0</div>
                        <div class="stat-label">إجمالي الحفر المكتشفة</div>
                    </div>

                    <!-- System Info -->
                    <div class="card" style="padding:20px;">
                        <div class="card-header" style="padding:0 0 12px; border:none;">⚙️ معلومات النظام</div>
                        <div class="info-row">
                            <span class="label">الكاميرات</span>
                            <span class="value" id="cam-count">0</span>
                        </div>
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

            <div class="footer">
                Vision + Voice AI Assistant &copy; 2026 — Jetson Orin Nano
            </div>

            <script>
                function updateDashboard() {
                    fetch('/api/status')
                        .then(r => r.json())
                        .then(data => {
                            // Status
                            const statusEl = document.getElementById('sys-status');
                            const badge = document.getElementById('status-badge');
                            statusEl.innerText = data.status === 'running' ? 'يعمل' : 'متوقف';
                            
                            // Pothole count
                            document.getElementById('ph-count').innerText = data.pothole_detections;
                            
                            // Model badge
                            const modelBadge = document.getElementById('ph-model-badge');
                            if (data.pothole_model_loaded) {
                                modelBadge.className = 'model-status loaded';
                                modelBadge.innerHTML = '✅ محمّل وجاهز';
                            } else {
                                modelBadge.className = 'model-status not-loaded';
                                modelBadge.innerHTML = '❌ غير محمّل';
                            }

                            // Cameras
                            document.getElementById('cam-count').innerText = data.cameras_active || 0;
                        })
                        .catch(() => {});
                }
                
                updateDashboard();
                setInterval(updateDashboard, 3000);
            </script>
        </body>
    </html>
    """
    return html

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/api/status")
def status():
    return jsonify(system_state)

@app.route("/setup")
def setup_page():
    html = """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>إعدادات النظام (Wi-Fi & Bluetooth)</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Inter', sans-serif; background: #0f0f1a; color: #e0e0e0; margin: 0; padding: 20px; }
            h1 { text-align: center; color: #6c5ce7; margin-bottom: 30px; }
            .card { background: rgba(25, 25, 50, 0.8); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; margin-bottom: 20px; }
            button { background: #6c5ce7; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-family: 'Inter'; font-weight: 600; margin-bottom: 15px; }
            button:hover { background: #5a4bcf; }
            .list-item { display: flex; justify-content: space-between; align-items: center; padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }
            .list-item:last-child { border-bottom: none; }
            input { background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.2); color: white; padding: 8px; border-radius: 6px; margin-left: 10px; }
            .btn-connect { background: #00cec9; padding: 6px 12px; }
            .btn-connect:hover { background: #00b5b1; }
            a.back { color: #8888aa; text-decoration: none; display: inline-block; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <a href="/" class="back">← العودة للوحة التحكم</a>
        <h1>⚙️ إعدادات الاتصال</h1>
        
        <div class="card">
            <h2>📶 شبكات Wi-Fi المتاحة</h2>
            <button onclick="scanWifi()">بحث عن شبكات</button>
            <div id="wifi-list"></div>
        </div>

        <div class="card">
            <h2>🎧 أجهزة البلوتوث</h2>
            <button onclick="scanBt()">بحث عن أجهزة</button>
            <div id="bt-list"></div>
        </div>

        <script>
            function scanWifi() {
                const list = document.getElementById('wifi-list');
                list.innerHTML = '<p>جاري البحث...</p>';
                fetch('/api/wifi/scan').then(r => r.json()).then(data => {
                    list.innerHTML = '';
                    if (data.length === 0) list.innerHTML = '<p>لا يوجد شبكات.</p>';
                    data.forEach(net => {
                        list.innerHTML += `
                            <div class="list-item">
                                <div>
                                    <strong>${net.ssid}</strong> <small>(${net.signal}%)</small>
                                </div>
                                <div>
                                    ${net.security !== 'Open' ? `<input type="password" id="pass-${net.ssid}" placeholder="الرقم السري">` : ''}
                                    <button class="btn-connect" onclick="connectWifi('${net.ssid}', ${net.security !== 'Open'})">اتصال</button>
                                </div>
                            </div>
                        `;
                    });
                });
            }

            function connectWifi(ssid, hasPass) {
                const pass = hasPass ? document.getElementById(`pass-${ssid}`).value : null;
                alert('جاري الاتصال... قد ينقطع الاتصال بجهازك الجتسن بعد ثوانٍ لو نجح الاتصال بالشبكة الجديدة.');
                fetch('/api/wifi/connect', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ssid: ssid, password: pass})
                }).then(r => r.json()).then(data => {
                    alert(data.message);
                });
            }

            function scanBt() {
                const list = document.getElementById('bt-list');
                list.innerHTML = '<p>جاري البحث (قد يستغرق 5 ثواني)...</p>';
                fetch('/api/bt/scan').then(r => r.json()).then(data => {
                    list.innerHTML = '';
                    if (data.length === 0) list.innerHTML = '<p>لا يوجد أجهزة.</p>';
                    data.forEach(dev => {
                        list.innerHTML += `
                            <div class="list-item">
                                <div>
                                    <strong>${dev.name}</strong> <small>(${dev.mac})</small><br>
                                    <span style="color:${dev.connected ? '#00cec9' : '#888'}">${dev.connected ? 'متصل' : 'غير متصل'}</span>
                                </div>
                                <button class="btn-connect" onclick="connectBt('${dev.mac}')">اقتران واتصال</button>
                            </div>
                        `;
                    });
                });
            }

            function connectBt(mac) {
                alert('جاري الاقتران والاتصال...');
                fetch('/api/bt/connect', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({mac: mac})
                }).then(r => r.json()).then(data => {
                    alert(data.message);
                    scanBt();
                });
            }
        </script>
    </body>
    </html>
    """
    return html

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

# Captive Portal Catch-all: Redirect any 404 to /setup
@app.errorhandler(404)
def page_not_found(e):
    return redirect("/setup")

def run_server():
    app.run(host="0.0.0.0", port=config.WEB_PORT, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_server()
