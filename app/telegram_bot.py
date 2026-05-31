"""
Telegram Bot Module.

Sends sensor data, detection alerts, and FALL ALERTS to Telegram.
Uses the Telegram Bot API directly via requests (no extra dependencies).
"""

import requests
import threading
import time
import json
import queue


class TelegramBot:
    def __init__(self, token, send_interval=30):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.chat_ids = set()
        self.send_interval = send_interval
        self._running = False
        self._thread = None
        self._arduino_reader = None
        self._last_detection = ""
        self._lock = threading.Lock()
        self.message_queue = queue.Queue()
        self._sender_thread = None

        # Verify bot connection
        self._verify_bot()

    def _verify_bot(self):
        """Verify the bot token and print bot info."""
        try:
            resp = requests.get(f"{self.base_url}/getMe", timeout=10)
            data = resp.json()
            if data.get("ok"):
                bot_info = data["result"]
                print(f"Telegram Bot: Connected as @{bot_info.get('username', '?')}")
            else:
                print(f"Telegram Bot: Token verification failed - {data}")
        except Exception as e:
            print(f"Telegram Bot: Connection error - {e}")

    def _get_updates(self):
        """Get new messages to discover chat IDs and handle commands."""
        try:
            resp = requests.get(
                f"{self.base_url}/getUpdates",
                params={"timeout": 5, "allowed_updates": json.dumps(["message", "callback_query"])},
                timeout=15
            )
            data = resp.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    # Handle Callback Query
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        print(f"Telegram Bot: Callback Query received: {cb.get('data')}")
                        if cb.get("data") == "stop_alarm":
                            chat_id = cb.get("message", {}).get("chat", {}).get("id")
                            if chat_id:
                                self._handle_buzzer_command(chat_id, False)
                            try:
                                requests.post(f"{self.base_url}/answerCallbackQuery", json={"callback_query_id": cb["id"]})
                            except: pass
                        continue

                    msg = update.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "")

                    if chat_id and chat_id not in self.chat_ids:
                        self.chat_ids.add(chat_id)
                        user = msg.get("from", {})
                        name = user.get("first_name", "مستخدم")
                        print(f"Telegram Bot: New user - {name} (chat_id: {chat_id})")
                        self.send_message(
                            chat_id,
                            f"مرحباً {name}! 👋\n"
                            f"تم تسجيلك في نظام السلامة الذكي.\n"
                            f"سيتم إرسال تنبيهات السقوط وبيانات الحساسات إليك.\n\n"
                            f"أرسل /help لعرض الأوامر."
                        )

                    # Handle commands
                    if text == "/start":
                        pass  # Already handled above
                    elif text == "/status":
                        self._handle_status_command(chat_id)
                    elif text == "/sensors":
                        self._handle_sensors_command(chat_id)
                    elif text == "/location":
                        self._handle_location_command(chat_id)
                    elif text == "/buzzer_on":
                        self._handle_buzzer_command(chat_id, True)
                    elif text == "/buzzer_off":
                        self._handle_buzzer_command(chat_id, False)
                    elif text == "/help":
                        self._handle_help_command(chat_id)

                # Acknowledge processed updates
                if data.get("result"):
                    last_id = data["result"][-1]["update_id"]
                    requests.get(
                        f"{self.base_url}/getUpdates",
                        params={"offset": last_id + 1, "timeout": 0},
                        timeout=10
                    )
        except Exception:
            pass

    def _handle_help_command(self, chat_id):
        """Send help message."""
        help_text = (
            "🤖 *أوامر البوت:*\n\n"
            "📊 /sensors - بيانات الحساسات الحالية\n"
            "📸 /status - حالة الكشف بالكاميرا\n"
            "📍 /location - الموقع الحالي\n"
            "🔔 /buzzer\\_on - تشغيل البزر\n"
            "🔕 /buzzer\\_off - إيقاف البزر\n"
            "❓ /help - عرض الأوامر\n\n"
            "⚠️ سيتم إرسال تنبيه فوري في حالة السقوط!"
        )
        self.send_message(chat_id, help_text)

    def _handle_status_command(self, chat_id):
        """Send current detection status."""
        with self._lock:
            detection = self._last_detection
        if detection:
            self.send_message(chat_id, f"📸 *آخر كشف:*\n{detection}")
        else:
            self.send_message(chat_id, "📸 لا يوجد كشف حالياً.")

    def _handle_sensors_command(self, chat_id):
        """Send current sensor data."""
        if self._arduino_reader:
            msg = self._arduino_reader.get_telegram_message()
            if msg:
                self.send_message(chat_id, msg)
            else:
                self.send_message(chat_id, "⚠️ لا توجد بيانات من الحساسات.")
        else:
            self.send_message(chat_id, "⚠️ الأردوينو غير متصل.")

    def _handle_location_command(self, chat_id):
        """Send current GPS location."""
        if self._arduino_reader:
            lat, lon = self._arduino_reader.get_gps()
            if lat and lon:
                self.send_location(chat_id, lat, lon)
            else:
                self.send_message(chat_id, "📍 لا توجد إشارة GPS حالياً.")
        else:
            self.send_message(chat_id, "⚠️ الأردوينو غير متصل.")

    def _handle_buzzer_command(self, chat_id, on):
        """Control buzzer remotely."""
        if self._arduino_reader:
            if on:
                self._arduino_reader.buzzer_on()
                self.send_message(chat_id, "🔔 تم تشغيل البزر.")
            else:
                self._arduino_reader.alert_off()
                self.send_message(chat_id, "🔕 تم إيقاف البزر.")
        else:
            self.send_message(chat_id, "⚠️ الأردوينو غير متصل.")

    # =================== Send Methods (Asynchronous Queueing) ===================

    def send_message(self, chat_id, text, reply_markup=None):
        """Queue a text message to be sent asynchronously."""
        self.message_queue.put({
            "type": "message",
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup
        })

    def _execute_send_message(self, chat_id, text, reply_markup=None):
        """Execute the actual API request to send a message."""
        try:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
                
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json=payload,
                timeout=10
            )
            data = resp.json()
            if not data.get("ok"):
                print(f"Telegram Bot: Send failed - {data}")
        except Exception as e:
            print(f"Telegram Bot: Send Exception - {e}")

    def send_location(self, chat_id, latitude, longitude):
        """Queue a GPS location pin to be sent asynchronously."""
        self.message_queue.put({
            "type": "location",
            "chat_id": chat_id,
            "latitude": latitude,
            "longitude": longitude
        })

    def _execute_send_location(self, chat_id, latitude, longitude):
        """Execute the actual API request to send location."""
        try:
            requests.post(
                f"{self.base_url}/sendLocation",
                json={
                    "chat_id": chat_id,
                    "latitude": latitude,
                    "longitude": longitude,
                },
                timeout=10
            )
        except Exception as e:
            print(f"Telegram Bot: Send location failed - {e}")

    def broadcast(self, text, reply_markup=None):
        """Send a message to all registered chats."""
        for chat_id in self.chat_ids.copy():
            self.send_message(chat_id, text, reply_markup)

    def broadcast_location(self, latitude, longitude):
        """Send location to all registered chats."""
        for chat_id in self.chat_ids.copy():
            self.send_location(chat_id, latitude, longitude)

    def send_photo(self, chat_id, photo_path, caption=None):
        """Queue a photo file to be sent asynchronously."""
        self.message_queue.put({
            "type": "photo",
            "chat_id": chat_id,
            "photo_path": photo_path,
            "caption": caption
        })

    def _execute_send_photo(self, chat_id, photo_path, caption=None):
        """Execute the actual API request to send a photo."""
        try:
            with open(photo_path, "rb") as photo:
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                requests.post(
                    f"{self.base_url}/sendPhoto",
                    data=data,
                    files={"photo": photo},
                    timeout=15,
                )
        except Exception as e:
            print(f"Telegram Bot: Send photo failed - {e}")

    def broadcast_photo(self, photo_path, caption=None):
        """Send a photo to all registered chats."""
        for chat_id in self.chat_ids.copy():
            self.send_photo(chat_id, photo_path, caption)

    # =================== Fall Alert ===================

    def send_fall_alert(self, fall_info):
        """
        Send emergency fall alert to all users.
        
        fall_info dict:
          person_name, person_age, person_id, lat, lon, gps_fix, time
        """
        name = fall_info.get("person_name", "غير معروف")
        age = fall_info.get("person_age", "?")
        pid = fall_info.get("person_id", "?")
        lat = fall_info.get("lat", 0)
        lon = fall_info.get("lon", 0)
        gps_fix = fall_info.get("gps_fix", False)
        fall_time = fall_info.get("time", "")

        alert_msg = (
            "🚨🚨🚨 *تنبيه سقوط!* 🚨🚨🚨\n\n"
            f"👤 *الاسم:* {name}\n"
            f"🎂 *العمر:* {age} سنة\n"
            f"🆔 *الرقم:* {pid}\n"
            f"⏰ *الوقت:* {fall_time}\n\n"
        )

        if gps_fix and (lat != 0 or lon != 0):
            maps_link = f"https://www.google.com/maps?q={lat},{lon}"
            alert_msg += f"📍 *الموقع:* [{lat:.6f}, {lon:.6f}]({maps_link})\n"
        else:
            alert_msg += "📍 *الموقع:* لا توجد إشارة GPS\n"

        alert_msg += "\n⚠️ يرجى التحقق من سلامة الشخص فوراً!"

        # Create inline keyboard for stop button
        keyboard = {
            "inline_keyboard": [[
                {"text": "🔕 إيقاف الإنذار (Stop Alarm)", "callback_data": "stop_alarm"}
            ]]
        }

        # Send alert message to all users
        self.broadcast(alert_msg, reply_markup=keyboard)

        # Send location pin if GPS is available
        if gps_fix and (lat != 0 or lon != 0):
            self.broadcast_location(lat, lon)

        print(f"Telegram Bot: Fall alert sent to {len(self.chat_ids)} users!")

    # =================== Integration ===================

    def set_arduino_reader(self, arduino_reader):
        """Link the Arduino reader for sensor data."""
        self._arduino_reader = arduino_reader

    def update_detection(self, detection_text):
        """Update the latest detection info."""
        with self._lock:
            self._last_detection = detection_text

    def start(self):
        """Start the bot."""
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
        self._sender_thread = threading.Thread(target=self._sender_loop, daemon=True)
        self._sender_thread.start()
        
        print(f"Telegram Bot: Started (auto-send every {self.send_interval}s)")

    def stop(self):
        """Stop the bot."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._sender_thread:
            self._sender_thread.join(timeout=5)
        print("Telegram Bot: Stopped.")

    def _sender_loop(self):
        """Dedicated thread to process and send queued messages."""
        while self._running:
            try:
                task = self.message_queue.get(timeout=1)
                self._process_task(task)
                self.message_queue.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                print(f"Telegram Bot: Sender loop error - {e}")

    def _process_task(self, task):
        task_type = task.get("type")
        if task_type == "message":
            self._execute_send_message(task["chat_id"], task["text"], task.get("reply_markup"))
        elif task_type == "location":
            self._execute_send_location(task["chat_id"], task["latitude"], task["longitude"])
        elif task_type == "photo":
            self._execute_send_photo(task["chat_id"], task["photo_path"], task.get("caption"))

    def _run_loop(self):
        """Main loop: check messages, send periodic data."""
        last_send_time = 0

        while self._running:
            self._get_updates()

            now = time.time()
            if self.send_interval > 0 and now - last_send_time >= self.send_interval and self.chat_ids:
                if self._arduino_reader:
                    msg = self._arduino_reader.get_telegram_message()
                    if msg:
                        self.broadcast(msg)
                        last_send_time = now

            time.sleep(2)
