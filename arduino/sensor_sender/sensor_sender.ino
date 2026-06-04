/*
 * Arduino Nano - Smart Safety System
 * 
 * Sensors: MPU6050, HC-SR04, GPS (NEO-6M), Buzzer, Vibration Motor
 * 
 * Sends JSON data every second over Serial (115200 baud)
 * Receives commands from Jetson via Serial
 * 
 * Commands:
 *   b1 / b0    -> Buzzer ON / OFF
 *   v1 / v0    -> Vibration ON / OFF
 *   a1 / a0    -> Auto proximity alarm ON / OFF
 *   d50        -> Set alarm distance to 50cm
 *   alert      -> Turn ON both buzzer + vibration (fall alert)
 *   stop       -> Turn OFF both buzzer + vibration
 *   r          -> Force send readings now
 */

#include <Wire.h>
#include <SoftwareSerial.h>

// GPS
SoftwareSerial gpsSerial(4, 3);
// GPS TX -> D4, GPS RX -> D3

// MPU6050
#define MPU_ADDR 0x68

// Pins
#define BUZZER_PIN 12
#define TRIG_PIN 6
#define ECHO_PIN 7
#define VIB_PIN 5

bool buzzerState = false;
bool vibState = false;
bool aiBuzzerState = false;
bool aiVibState = false;
bool autoAlarm = true;
int vibIntensity = 255;       // PWM intensity (0-255) - default MAX
bool vibPulseMode = true;     // Pulse mode for stronger feel
unsigned long lastPulse = 0;
bool pulseHigh = true;

int alarmDistance = 50;   // cm
float distanceCm = -1;

unsigned long lastSend = 0;
unsigned long lastUltra = 0;

int16_t ax, ay, az, tempRaw, gx, gy, gz;
bool mpuOk = false;

String command = "";

// GPS parsing
char gpsBuffer[120];
int gpsIdx = 0;
float gpsLat = 0.0;
float gpsLon = 0.0;
bool gpsFix = false;

void setup() {
  Serial.begin(115200);
  gpsSerial.begin(9600);

  Wire.begin();

  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(VIB_PIN, OUTPUT);

  digitalWrite(BUZZER_PIN, LOW);
  analogWrite(VIB_PIN, 0);

  // Wake up MPU6050
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);
  Wire.write(0);
  byte error = Wire.endTransmission(true);
  mpuOk = (error == 0);

  delay(500);
  
  // Send ready signal as JSON
  Serial.println("{\"status\":\"ready\",\"mpu\":" + String(mpuOk ? "true" : "false") + "}");
}

void updateOutputStates() {
  bool ultraAlarm = false;
  if (autoAlarm) {
    if (distanceCm > 0 && distanceCm <= alarmDistance) {
      ultraAlarm = true;
    }
  }

  buzzerState = aiBuzzerState || ultraAlarm;
  vibState = aiVibState || ultraAlarm;
}

void loop() {
  readSerialCommand();
  processGPS();

  // Read ultrasonic every 100ms
  if (millis() - lastUltra >= 100) {
    lastUltra = millis();
    distanceCm = readUltrasonicCM();

    updateOutputStates();
    applyOutputs();
  }

  // Send JSON data every second
  if (millis() - lastSend >= 1000) {
    lastSend = millis();
    sendJSON();
  }
}

// ================= GPS =================
void processGPS() {
  while (gpsSerial.available()) {
    char c = gpsSerial.read();
    
    if (c == '\n') {
      gpsBuffer[gpsIdx] = '\0';
      
      // Parse GPRMC or GNRMC
      if (strncmp(gpsBuffer, "$GPRMC", 6) == 0 || strncmp(gpsBuffer, "$GNRMC", 6) == 0) {
        parseGPRMC();
      }
      
      gpsIdx = 0;
    } else if (c != '\r' && gpsIdx < 118) {
      gpsBuffer[gpsIdx++] = c;
    }
  }
}

void parseGPRMC() {
  // $GPRMC,time,status,lat,N/S,lon,E/W,...
  char* token;
  char buf[120];
  strncpy(buf, gpsBuffer, 119);
  buf[119] = '\0';
  
  char* fields[13];
  int fieldCount = 0;
  
  token = strtok(buf, ",");
  while (token != NULL && fieldCount < 13) {
    fields[fieldCount++] = token;
    token = strtok(NULL, ",");
  }
  
  if (fieldCount < 7) return;
  
  // Check status: A = valid
  if (fields[2][0] != 'A') {
    gpsFix = false;
    return;
  }
  
  // Parse latitude: ddmm.mmmm
  float rawLat = atof(fields[3]);
  int latDeg = (int)(rawLat / 100);
  float latMin = rawLat - latDeg * 100.0;
  gpsLat = latDeg + latMin / 60.0;
  if (fields[4][0] == 'S') gpsLat = -gpsLat;
  
  // Parse longitude: dddmm.mmmm
  float rawLon = atof(fields[5]);
  int lonDeg = (int)(rawLon / 100);
  float lonMin = rawLon - lonDeg * 100.0;
  gpsLon = lonDeg + lonMin / 60.0;
  if (fields[6][0] == 'W') gpsLon = -gpsLon;
  
  gpsFix = true;
}

// ================= Serial Control =================
void readSerialCommand() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      command.trim();
      if (command.length() > 0) {
        handleCommand(command);
        command = "";
      }
    } else {
      command += c;
    }
  }
}

void handleCommand(String cmd) {
  cmd.trim();
  cmd.toLowerCase();

  if (cmd == "b1") {
    aiBuzzerState = true;
    Serial.println("{\"cmd\":\"b1\",\"ok\":true}");
  } 
  else if (cmd == "b0") {
    aiBuzzerState = false;
    Serial.println("{\"cmd\":\"b0\",\"ok\":true}");
  } 
  else if (cmd == "v1") {
    aiVibState = true;
    Serial.println("{\"cmd\":\"v1\",\"ok\":true}");
  } 
  else if (cmd == "v0") {
    aiVibState = false;
    Serial.println("{\"cmd\":\"v0\",\"ok\":true}");
  } 
  else if (cmd == "a1") {
    autoAlarm = true;
    Serial.println("{\"cmd\":\"a1\",\"ok\":true}");
  } 
  else if (cmd == "a0") {
    autoAlarm = false;
    Serial.println("{\"cmd\":\"a0\",\"ok\":true}");
  } 
  else if (cmd.startsWith("d")) {
    int value = cmd.substring(1).toInt();
    if (value > 0) {
      alarmDistance = value;
      Serial.println("{\"cmd\":\"d\",\"val\":" + String(alarmDistance) + ",\"ok\":true}");
    }
  } 
  else if (cmd == "alert") {
    // Emergency: turn on both buzzer and vibration
    aiBuzzerState = true;
    aiVibState = true;
    Serial.println("{\"cmd\":\"alert\",\"ok\":true}");
  }
  else if (cmd == "stop") {
    // Stop all AI outputs
    aiBuzzerState = false;
    aiVibState = false;
    Serial.println("{\"cmd\":\"stop\",\"ok\":true}");
  }
  else if (cmd == "r") {
    sendJSON();
    return;  // Already sent data
  } 
  else {
    Serial.println("{\"cmd\":\"unknown\",\"ok\":false}");
  }

  updateOutputStates();
  applyOutputs();
}

// ================= Outputs =================
void applyOutputs() {
  digitalWrite(BUZZER_PIN, buzzerState ? HIGH : LOW);
  
  if (vibState) {
    if (vibPulseMode) {
      // Rapid pulse between HIGH and MED for stronger physical feel
      if (millis() - lastPulse >= 40) {
        lastPulse = millis();
        pulseHigh = !pulseHigh;
      }
      analogWrite(VIB_PIN, pulseHigh ? 255 : 180);
    } else {
      analogWrite(VIB_PIN, vibIntensity);
    }
  } else {
    analogWrite(VIB_PIN, 0);
  }
}

// ================= Ultrasonic =================
float readUltrasonicCM() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);

  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 25000UL);

  if (duration == 0) return -1;
  return duration / 58.0;
}

// ================= MPU6050 =================
bool readMPU6050() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);

  if (Wire.endTransmission(false) != 0) return false;

  Wire.requestFrom(MPU_ADDR, 14, true);
  if (Wire.available() < 14) return false;

  ax = Wire.read() << 8 | Wire.read();
  ay = Wire.read() << 8 | Wire.read();
  az = Wire.read() << 8 | Wire.read();
  tempRaw = Wire.read() << 8 | Wire.read();
  gx = Wire.read() << 8 | Wire.read();
  gy = Wire.read() << 8 | Wire.read();
  gz = Wire.read() << 8 | Wire.read();

  return true;
}

// ================= JSON Output =================
void sendJSON() {
  readMPU6050();

  Serial.print("{\"d\":");
  Serial.print(distanceCm, 1);
  
  Serial.print(",\"ax\":");
  Serial.print(ax);
  Serial.print(",\"ay\":");
  Serial.print(ay);
  Serial.print(",\"az\":");
  Serial.print(az);
  
  Serial.print(",\"gx\":");
  Serial.print(gx);
  Serial.print(",\"gy\":");
  Serial.print(gy);
  Serial.print(",\"gz\":");
  Serial.print(gz);
  
  Serial.print(",\"lat\":");
  Serial.print(gpsLat, 6);
  Serial.print(",\"lon\":");
  Serial.print(gpsLon, 6);
  Serial.print(",\"gps\":");
  Serial.print(gpsFix ? "true" : "false");
  
  Serial.print(",\"buz\":");
  Serial.print(buzzerState ? 1 : 0);
  Serial.print(",\"vib\":");
  Serial.print(vibState ? 1 : 0);
  Serial.print(",\"auto\":");
  Serial.print(autoAlarm ? 1 : 0);
  Serial.print(",\"ad\":");
  Serial.print(alarmDistance);
  
  Serial.println("}");
}
