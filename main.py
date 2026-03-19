from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtCore import QTimer, QThread
import sys, io, time, os
import folium
import pyqtgraph as pg
from collections import deque
from serial.tools import list_ports

from ui_mainwindow import Ui_MainWindow
from services.uart_reader import SerialController, HYISerial
from core.byte_converter import ByteConverter
from config.settings import get_serial_config
from core.packet_builder import build_combined_packet
from PyQt5.QtWebEngineWidgets import QWebEngineView

from services.serial_worker import SerialIOSupervisor
from services.model_loader import ModelViewer

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # 3D orientation widget: bare QOpenGLWidget yerine ModelViewer koy
        self._init_3d_viewer()

        # Harita & grafikler
        self.initMap()
        self.initGraphs()

        # --- Controller'ları oluştur ---
        cfg = get_serial_config()
        self.controller       = SerialController(**cfg["ANA"])     # ANA
        self.gorev_controller = SerialController(**cfg["GOREV"])   # GÖREV
        self.inscontroller    = SerialController(**cfg["INS"])     # INS
        self.hyicontroller    = HYISerial(**cfg["HAKEM"])          # HAKEM

        # Auto-reconnect bayrakları + hedefler
        self._auto_main = False;    self._desired_main_port = None;    self._desired_main_baud = None
        self._auto_payload = False; self._desired_payload_port = None; self._desired_payload_baud = None
        self._auto_ins = False;     self._desired_ins_port = None;     self._desired_ins_baud = None
        self._auto_judge = False;   self._desired_judge_port = None;   self._desired_judge_baud = None

        self._known_ports = set()
        self._init_config_tab()

        # Faz/sayaç
        self.updateFlightPhase("ready")
        self.packet_counter = 0
        self.map_timer = time.time()

        # --- Operasyonel durum takibi ---
        self._last_main_pkt_time = None   # son ANA paket zamanı
        self._last_payload_pkt_time = None
        self._decode_error_count = 0
        self._last_error_msg = ""

        # --- Basit faz otomasyonu için ---
        self.phase = "ready"
        self._boost_t0 = None  # boost'un ilk yandığı an (coast'a 4 sn sonra geçmek için)

        # ---- I/O Worker Thread ----
        self.io_thread = QThread(self)
        self.io_worker = SerialIOSupervisor(
            self.controller, self.gorev_controller, self.inscontroller, self.hyicontroller,
            main_size=84, payload_size=26, ins_size=75, read_hz=10, send_hz=5
        )
        self.io_worker.moveToThread(self.io_thread)

        # Signals <-> Slots
        self.io_thread.started.connect(self.io_worker.start)
        self.io_worker.main_packet.connect(self._on_main_packet)
        self.io_worker.payload_pkt.connect(self._on_payload_packet)
        self.io_worker.ins_packet.connect(self._on_ins_packet)
        self.io_worker.error.connect(self._log_error)

        # Kapatmada düzgün stop
        self.destroyed.connect(lambda: (self.io_worker.stop(), self.io_thread.quit(), self.io_thread.wait()))

        self.io_thread.start()

        # Auto-reconnect ve COM tarama zamanlayıcıları (hafif işler GUI'de kalır)
        self.reconnectTimer = QTimer(self)
        self.reconnectTimer.timeout.connect(self._auto_reconnect_tick)
        self.reconnectTimer.start(1500)

        self.portScanTimer = QTimer(self)
        self.portScanTimer.timeout.connect(self._scan_ports)
        self.portScanTimer.start(2000)

        # Status bar güncelleme zamanlayıcısı
        self._statusTimer = QTimer(self)
        self._statusTimer.timeout.connect(self._refresh_statusbar)
        self._statusTimer.start(1000)

    # -------------------- Config Tab --------------------
    def _init_config_tab(self):
        # Port listelerini doldur
        def fill_ports(cb):
            cb.clear()
            ports = [p.device for p in list_ports.comports()]
            if not ports:
                ports = ["COM1", "COM2"]
            cb.addItems(ports)

        fill_ports(self.cbMainPort);      self.cbMainBaud.addItems(["9600", "115200"])
        fill_ports(self.cbPayloadPort);   self.cbPayloadBaud.addItems(["9600", "115200"])
        fill_ports(self.cbInsPort);       self.cbInsBaud.addItems(["9600", "115200"])
        fill_ports(self.cbJudgePort);     self.cbJudgeBaud.addItems(["19200", "9600", "115200"])

        # Varsayılanlar
        cfg = get_serial_config()
        self.cbMainPort.setCurrentText(cfg["ANA"]["port"])
        self.cbMainBaud.setCurrentText(str(cfg["ANA"]["baudrate"]))
        self.cbPayloadPort.setCurrentText(cfg["GOREV"]["port"])
        self.cbPayloadBaud.setCurrentText(str(cfg["GOREV"]["baudrate"]))
        self.cbInsPort.setCurrentText(cfg["INS"]["port"])
        self.cbInsBaud.setCurrentText(str(cfg["INS"]["baudrate"]))
        self.cbJudgePort.setCurrentText(cfg["HAKEM"]["port"])
        self.cbJudgeBaud.setCurrentText(str(cfg["HAKEM"]["baudrate"]))

        # Start/Stop bağla
        self.btnMainStart.clicked.connect(self._open_main)
        self.btnMainStop.clicked.connect(self._close_main)

        self.btnPayloadStart.clicked.connect(self._open_payload)
        self.btnPayloadStop.clicked.connect(self._close_payload)

        self.btnInsStart.clicked.connect(self._open_ins)
        self.btnInsStop.clicked.connect(self._close_ins)

        self.btnJudgeStart.clicked.connect(self._open_judge)
        self.btnJudgeStop.clicked.connect(self._close_judge)

        # Etiketler
        self._set_status(self.lblMainStatus,    "CLOSED")
        self._set_status(self.lblPayloadStatus, "CLOSED")
        self._set_status(self.lblInsStatus,     "CLOSED")
        self._set_status(self.lblJudgeStatus,   "CLOSED")

    # ---- Start/Stop yardımcıları ----
    def _set_status(self, label, text): label.setText(text)

    def _open_main(self):
        self._auto_main = True
        self._desired_main_port = self.cbMainPort.currentText()
        self._desired_main_baud = int(self.cbMainBaud.currentText())
        ok = self.controller.open(port=self._desired_main_port, baudrate=self._desired_main_baud)
        self._set_status(self.lblMainStatus, "OPEN" if ok else "RETRYING...")

    def _close_main(self):
        self._auto_main = False
        self.controller.close()
        self._set_status(self.lblMainStatus, "CLOSED")

    def _open_payload(self):
        self._auto_payload = True
        self._desired_payload_port = self.cbPayloadPort.currentText()
        self._desired_payload_baud = int(self.cbPayloadBaud.currentText())
        ok = self.gorev_controller.open(port=self._desired_payload_port, baudrate=self._desired_payload_baud)
        self._set_status(self.lblPayloadStatus, "OPEN" if ok else "RETRYING...")

    def _close_payload(self):
        self._auto_payload = False
        self.gorev_controller.close()
        self._set_status(self.lblPayloadStatus, "CLOSED")

    def _open_ins(self):
        self._auto_ins = True
        self._desired_ins_port = self.cbInsPort.currentText()
        self._desired_ins_baud = int(self.cbInsBaud.currentText())
        ok = self.inscontroller.open(port=self._desired_ins_port, baudrate=self._desired_ins_baud)
        self._set_status(self.lblInsStatus, "OPEN" if ok else "RETRYING...")

    def _close_ins(self):
        self._auto_ins = False
        self.inscontroller.close()
        self._set_status(self.lblInsStatus, "CLOSED")

    def _open_judge(self):
        self._auto_judge = True
        self._desired_judge_port = self.cbJudgePort.currentText()
        self._desired_judge_baud = int(self.cbJudgeBaud.currentText())
        ok = self.hyicontroller.open(port=self._desired_judge_port, baudrate=self._desired_judge_baud)
        self._set_status(self.lblJudgeStatus, "OPEN" if ok else "RETRYING...")

    def _close_judge(self):
        self._auto_judge = False
        self.hyicontroller.disconnect()
        self._set_status(self.lblJudgeStatus, "CLOSED")

    # -------------------- Otomatik Yeniden Bağlama --------------------
    def _auto_reconnect_tick(self):
        if self._auto_main and self._desired_main_port:
            self.controller._desired_port = self._desired_main_port
            self.controller._desired_baud = self._desired_main_baud
            ok = self.controller.ensure_open()
            self._set_status(self.lblMainStatus, "OPEN" if ok else "RETRYING...")

        if self._auto_payload and self._desired_payload_port:
            self.gorev_controller._desired_port = self._desired_payload_port
            self.gorev_controller._desired_baud = self._desired_payload_baud
            ok = self.gorev_controller.ensure_open()
            self._set_status(self.lblPayloadStatus, "OPEN" if ok else "RETRYING...")

        if self._auto_ins and self._desired_ins_port:
            self.inscontroller._desired_port = self._desired_ins_port
            self.inscontroller._desired_baud = self._desired_ins_baud
            ok = self.inscontroller.ensure_open()
            self._set_status(self.lblInsStatus, "OPEN" if ok else "RETRYING...")

        if self._auto_judge and self._desired_judge_port:
            self.hyicontroller._desired_port = self._desired_judge_port
            self.hyicontroller._desired_baud = self._desired_judge_baud
            ok = self.hyicontroller.ensure_open()
            self._set_status(self.lblJudgeStatus, "OPEN" if ok else "RETRYING...")

    # -------------------- COM Port Tarama --------------------
    def _combo_items(self, combo: QtWidgets.QComboBox) -> list:
        return [combo.itemText(i) for i in range(combo.count())]

    def _refresh_ports_in_combobox(self, combo: QtWidgets.QComboBox, ports_list: list):
        current = combo.currentText()
        existing = [combo.itemText(i) for i in range(combo.count())]
        if existing == ports_list:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(ports_list)
        if current in ports_list:
            combo.setCurrentText(current)
        combo.blockSignals(False)

    def _scan_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self._refresh_ports_in_combobox(self.cbMainPort, ports)
        self._refresh_ports_in_combobox(self.cbPayloadPort, ports)
        self._refresh_ports_in_combobox(self.cbInsPort, ports)
        self._refresh_ports_in_combobox(self.cbJudgePort, ports)

        if self._desired_main_port and self._desired_main_port in ports:
            self.cbMainPort.setCurrentText(self._desired_main_port)
        if self._desired_payload_port and self._desired_payload_port in ports:
            self.cbPayloadPort.setCurrentText(self._desired_payload_port)
        if self._desired_ins_port and self._desired_ins_port in ports:
            self.cbInsPort.setCurrentText(self._desired_ins_port)
        if self._desired_judge_port and self._desired_judge_port in ports:
            self.cbJudgePort.setCurrentText(self._desired_judge_port)

        def mark(label, desired):
            if desired and desired not in ports:
                label.setText("RETRYING...")
        mark(self.lblMainStatus, self._desired_main_port)
        mark(self.lblPayloadStatus, self._desired_payload_port)
        mark(self.lblInsStatus, self._desired_ins_port)
        mark(self.lblJudgeStatus, self._desired_judge_port)

    # -------------------- UI Paket Handler'ları --------------------
    def _on_main_packet(self, pkt: bytes):
        try:
            # 6..70 arası float payload

            team_id = pkt[4]           # Byte5: UINT8
            counter = pkt[5]           # Byte6: UINT8
            raw_bytes = pkt[6:78]
            float_list = ByteConverter.bytes_to_float_list(raw_bytes)
        
            # Orientation (Euler: roll, pitch, yaw)
            self.widgetOrientation3D.orientationX = float_list[10]
            self.widgetOrientation3D.orientationY = float_list[11]
            self.widgetOrientation3D.orientationZ = float_list[12]

        # --- UI: integerleri integer olarak göster ---
            self.lblTeamIDValue.setText(str(team_id))
            self.lblCounterValue.setText(str(counter))  # %256 sarmalama gerekmiyor, zaten uint8

            self.lblAltitudeValue.setText(f"{float_list[0]:.2f} m")
            self.lblGPSAltitudeValue.setText(f"{float_list[1]:.2f} m")
            self.lblGPSLatitudeValue.setText(f"{float_list[2]:.6f} °")
            self.lblGPSLongitudeValue.setText(f"{float_list[3]:.6f} °")

            self.lblRocketGyroXValue.setText(f"{float_list[4]:.4f} ")
            self.lblRocketGyroYValue.setText(f"{float_list[5]:.4f} ")
            self.lblRocketGyroZValue.setText(f"{float_list[6]:.4f} ")
            self.lblRocketAccelXValue.setText(f"{float_list[7]:.4f} ")
            self.lblRocketAccelYValue.setText(f"{float_list[8]:.4f} ")
            self.lblRocketAccelZValue.setText(f"{float_list[9]:.4f} ")
            self.lblRocketYawValue.setText(f"{float_list[11]:.2f} ")

            self.lblTemperatureValue.setText(f"{float_list[13]:.2f} °C")

            self.lblBatteryStatusValue.setText(f"{float_list[15]:.2f} V")

            self.lblRSSIValue.setText(f"{float_list[16]:.2f} dBm")
            self.lblSNRValue.setText(f"{float_list[17]:.2f} dB")

            # --- GPS: satellites (UINT16) ---
            gps_satellites = (pkt[78] << 8) | pkt[79]          # high-low birleşimi
            self.lblSatelliteCountValue.setText(str(gps_satellites))

            status = pkt[80]   
            self.lblStatusValue.setText(str(status))

            # --- Basit faz otomasyonu ---
            alt = float_list[0]  # baro irtifa (m)

            # (İstersen drogue/main yine status ile yansısın)
            if status == 1:
                self.phase = "drogue"
            elif status == 3:
                self.phase = "main"
            else:
                # İrtifa kuralların:
                if alt <= 0.700:  # yerde tam sıfıra yaklaşınca
                    self.phase = "landed"
                    self._boost_t0 = None  # reset
                elif alt < 30:
                    self.phase = "ready"   # onground/ready
                    self._boost_t0 = None  # reset
                elif alt > 300.0:
                    # boost -> ilk kez bu banda girdiysek zaman damgası al
                    if self.phase != "boost" and self.phase != "coast":
                        self.phase = "boost"
                        self._boost_t0 = time.time()
                    # boost yandıktan 4 sn sonra -> coast
                    elif self.phase == "boost" and self._boost_t0 and (time.time() - self._boost_t0) >= 4.0:
                        self.phase = "coast"

            # LED’leri güncelle
            self.updateFlightPhase(self.phase)

            # Grafikler
            self.altitudeData.append(float_list[0])
            self.accelXData.append(float_list[7])
            self.accelYData.append(float_list[8])
            self.accelZData.append(float_list[9])
            self.yawData.append(float_list[11])

            # Harita (2 sn throttle)
            lat, lon = float_list[2], float_list[3]
            if time.time() - self.map_timer > 2:
                self.updateMap(lat, lon)
                self.map_timer = time.time()

            # Son paket zamanını kaydet
            self._last_main_pkt_time = time.time()

        except Exception as e:
            self._log_error(f"ANA decode: {e}")

    def _on_payload_packet(self, pkt: bytes):
        try:
            raw_bytes = pkt[6:30]
            f = ByteConverter.bytes_to_float_list(raw_bytes)
            self.lblPayloadGPSAltitudeValue.setText(f"{f[0]:.2f} m")
            self.lblPayloadGPSLatitudeValue.setText(f"{f[1]:.6f} °")
            self.lblPayloadGPSLongitudeValue.setText(f"{f[2]:.6f} °")
            self.lblPayloadRSSIValue.setText(f"{f[4]:.2f} dBm")
            self.lblPayloadSNRValue.setText(f"{f[5]:.2f} dB")
                        # --- GPS: satellites (UINT16) ---
            payloadgps_satellites = (pkt[30] << 8) | pkt[31]          # high-low birleşimi
            self.lblPayloadSatelliteValue.setText(str(payloadgps_satellites))
            self._last_payload_pkt_time = time.time()
        except Exception as e:
            self._log_error(f"GÖREV decode: {e}")

    def _on_ins_packet(self, pkt: bytes):
        try:
            raw_bytes = pkt[6:34]
            f1 = ByteConverter.bytes_to_float_list(raw_bytes)
            self.lblINSGPSLatitudeValue.setText(f"{f1[0]:.6f} °")
            self.lblINSGPSLongitudeValue.setText(f"{f1[1]:.6f} °")
            self.lblINSGPSAltitudeValue.setText(f"{f1[2]:.2f} m")

            self.lblINSlblSatelliteCountValue.setText(f"{f1[3]:.2f}")

            self.lblINSTemperatureValue.setText(f"{f1[4]:.2f}")

            self.lblINSRSSIValue.setText(f"{f1[5]:.2f} dBm")
            self.lblINSSNRValue.setText(f"{f1[6]:.2f} dB")
        except Exception as e:
            self._log_error(f"INS decode: {e}")

    # -------------------- Operasyonel Durum --------------------
    def _log_error(self, msg: str):
        """Hata mesajını hem konsola hem UI'a yansıt."""
        self._decode_error_count += 1
        self._last_error_msg = msg
        print(f"[ERR] {msg}")
        self.statusbar.showMessage(f"⚠ {msg}", 5000)

    def _refresh_statusbar(self):
        """Periyodik durum çubuğu güncellemesi."""
        parts = []

        # Son paket zamanı
        if self._last_main_pkt_time:
            elapsed = time.time() - self._last_main_pkt_time
            if elapsed > 5:
                parts.append(f"⚠ ANA: {elapsed:.0f}s önce (STALE)")
            else:
                parts.append(f"ANA: {elapsed:.1f}s önce")
        else:
            parts.append("ANA: paket yok")

        if self._last_payload_pkt_time:
            elapsed = time.time() - self._last_payload_pkt_time
            parts.append(f"GÖREV: {elapsed:.1f}s")

        # Hata sayacı
        if self._decode_error_count > 0:
            parts.append(f"Hata: {self._decode_error_count}")

        # Bağlantı durumları (kısa)
        ports = []
        if self._auto_main:
            ports.append("ANA:" + ("✓" if self.controller.is_open else "✗"))
        if self._auto_payload:
            ports.append("GRV:" + ("✓" if self.gorev_controller.is_open else "✗"))
        if self._auto_ins:
            ports.append("INS:" + ("✓" if self.inscontroller.is_open else "✗"))
        if self._auto_judge:
            ports.append("HKM:" + ("✓" if self.hyicontroller.is_connected else "✗"))
        if ports:
            parts.append(" ".join(ports))

        self.statusbar.showMessage("  |  ".join(parts))

    def closeApp(self):
        self.controller.close()
        self.close()

    # -------------------- Faz LED'leri --------------------
    def setPhaseActive(self, phaseLabel, color):
        phaseLabel.setStyleSheet(f"""
            QLabel {{
                min-width: 20px;
                min-height: 20px;
                border-radius: 10px;
                background-color: {color};
            }}
        """)

    def updateFlightPhase(self, phaseName):
        phases = {
            "ready": self.lblReadyIcon,
            "boost": self.lblBoostIcon,
            "coast": self.lblCoastIcon,
            "drogue": self.lblDrogueIcon,
            "main": self.lblMainIcon,
            "landed": self.lblLandedIcon,
        }
        for icon in phases.values(): self.setPhaseActive(icon, "red")
        if phaseName in phases: self.setPhaseActive(phases[phaseName], "lime")

    # -------------------- 3D Orientation --------------------
    def _init_3d_viewer(self):
        """Bare QOpenGLWidget'ı ModelViewer ile değiştir."""
        try:
            obj_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "assets", "3d_object", "falcon.obj"
            )
            viewer = ModelViewer(obj_path)

            # Layout'tan eski widget'ı çıkar, yenisini koy
            layout = self.gridLayout_28
            layout.replaceWidget(self.widgetOrientation3D, viewer)
            self.widgetOrientation3D.setParent(None)  # eski widget'ı sil
            self.widgetOrientation3D = viewer
            print("[3D] ModelViewer başarıyla yüklendi")
        except Exception as e:
            print(f"[3D] ModelViewer yüklenemedi, placeholder kalıyor: {e}")

    # -------------------- Harita --------------------
    def initMap(self, lat=40.0, lon=29.0):
        self.map = folium.Map(location=[lat, lon], zoom_start=13)
        folium.Marker([lat, lon], tooltip="Rocket").add_to(self.map)
        data = io.BytesIO(); self.map.save(data, close_file=False)
        html = data.getvalue().decode()

        # Leaflet map ve marker'ı global JS değişkenlerine ata
        # folium haritayı oluşturduktan sonra ilk map objesini yakala
        inject_js = """
        <script>
        var _rocketMap = null;
        var _rocketMarker = null;
        // folium map objesini bul (ilk L.map instance)
        (function() {
            var origMap = L.map;
            L.map = function() {
                _rocketMap = origMap.apply(this, arguments);
                L.map = origMap;  // sadece ilk çağrıyı yakala
                return _rocketMap;
            };
            var origMarker = L.marker;
            L.marker = function() {
                _rocketMarker = origMarker.apply(this, arguments);
                L.marker = origMarker;
                return _rocketMarker;
            };
        })();
        </script>
        """
        # Script'i </head> etiketinden hemen önce enjekte et
        html = html.replace("</head>", inject_js + "</head>")

        self.map_view = QWebEngineView(self.widgetMap)
        self.map_view.setHtml(html)
        self.map_view.setGeometry(0, 0, self.widgetMap.width(), self.widgetMap.height())
        self.map_view.show()

    def updateMap(self, lat, lon):
        # Tüm haritayı yeniden oluşturmak yerine JS ile marker ve view güncelle
        js = f"""
        if (_rocketMap && _rocketMarker) {{
            var ll = L.latLng({lat}, {lon});
            _rocketMarker.setLatLng(ll);
            _rocketMap.panTo(ll);
        }}
        """
        self.map_view.page().runJavaScript(js)

    def resizeEvent(self, event):
        if hasattr(self, "map_view"):
            self.map_view.setGeometry(0, 0, self.widgetMap.width(), self.widgetMap.height())
        super().resizeEvent(event)

    # -------------------- Grafikler --------------------
    def initGraphs(self):
        # Altitude
        layout_alt = QtWidgets.QVBoxLayout(self.widgetAltitudeGraph)
        self.altitudePlot = pg.PlotWidget(title="Altitude (m)")
        self.altitudePlot.setBackground('k')
        self.altitudeCurve = self.altitudePlot.plot(pen='y')
        self.altitudeData = deque(maxlen=600)
        layout_alt.addWidget(self.altitudePlot)

        # Acceleration
        layout_accel = QtWidgets.QVBoxLayout(self.widgetAccelXYZ)
        self.accelPlot = pg.PlotWidget(title="Acceleration (m/s²)")
        self.accelPlot.setBackground('k')
        self.accelXCurve = self.accelPlot.plot(pen='r', name="Accel X")
        self.accelYCurve = self.accelPlot.plot(pen='g', name="Accel Y")
        self.accelZCurve = self.accelPlot.plot(pen='b', name="Accel Z")
        self.accelXData, self.accelYData, self.accelZData = deque(maxlen=600), deque(maxlen=600), deque(maxlen=600)
        layout_accel.addWidget(self.accelPlot)

        # Yaw
        layout_yaw = QtWidgets.QVBoxLayout(self.widgetAngleZ)
        self.yawPlot = pg.PlotWidget(title="Angle Z (°)")
        self.yawPlot.setBackground('k')
        self.yawCurve = self.yawPlot.plot(pen='c')
        self.yawData = deque(maxlen=600)
        layout_yaw.addWidget(self.yawPlot)

        # Hız optimizasyonları
        try:
            for c in (self.altitudeCurve, self.accelXCurve, self.accelYCurve, self.accelZCurve, self.yawCurve):
                c.setClipToView(True)
                c.setDownsampling(auto=True, method='peak')
        except Exception:
            pass

        # --- Grafik güncelleme zamanlayıcısı (100 ms -> 10 FPS) ---
        self.plot_update_timer = QTimer(self)
        self.plot_update_timer.timeout.connect(self._refresh_plots)
        self.plot_update_timer.start(100)

    def _decimate(self, seq, target=1000):
        # Dinamik azaltma: hedef nokta sayısı civarında örnek üret
        try:
            n = len(seq)
        except TypeError:
            seq = list(seq); n = len(seq)
        step = max(1, n // max(1, target))
        if step <= 1:
            return list(seq)
        return list(seq)[::step]

    def _refresh_plots(self):
        # Görüntü yükünü azaltmak için dinamik decimate uygula
        self.altitudeCurve.setData(self._decimate(self.altitudeData))
        self.accelXCurve.setData(self._decimate(self.accelXData))
        self.accelYCurve.setData(self._decimate(self.accelYData))
        self.accelZCurve.setData(self._decimate(self.accelZData))
        self.yawCurve.setData(self._decimate(self.yawData))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())