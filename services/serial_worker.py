# services/serial_worker.py
from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot

# Bu worker, seri I/O'yu tek bir thread'de toplar: ANA, GÖREV, INS oku; HAKEM'e periyodik gönder.
class SerialIOSupervisor(QObject):
    # Çıktı sinyalleri (GUI'ye)
    main_packet  = pyqtSignal(bytes)   # ANA (ör. 75B)
    payload_pkt  = pyqtSignal(bytes)   # GÖREV (ör. 26B)
    ins_packet   = pyqtSignal(bytes)   # INS (opsiyonel)
    error        = pyqtSignal(str)

    def __init__(self, main_ctrl, payload_ctrl, ins_ctrl, judge_ctrl,
                 main_size=75, payload_size=26, ins_size=75,
                 read_hz=10, send_hz=5):
        super().__init__()
        self.main = main_ctrl
        self.payload = payload_ctrl
        self.ins = ins_ctrl
        self.judge = judge_ctrl

        self.main_size = int(main_size)
        self.payload_size = int(payload_size)
        self.ins_size = int(ins_size)

        self.counter = 0
        self._last_main = None
        our_last_payload = None
        self._last_payload = our_last_payload

        # Worker thread içi zamanlayıcılar
        self.read_timer = QTimer(self)
        self.read_timer.timeout.connect(self._poll_read)
        self.read_timer.setInterval(max(1, int(1000 / max(1, read_hz))))

        self.send_timer = QTimer(self)
        self.send_timer.timeout.connect(self._tick_send)
        self.send_timer.setInterval(max(1, int(1000 / max(1, send_hz))))

    # ---- Yaşam Döngüsü ----
    @pyqtSlot()
    def start(self):
        self.read_timer.start()
        self.send_timer.start()

    @pyqtSlot()
    def stop(self):
        self.read_timer.stop()
        self.send_timer.stop()

    # ---- Okuma ----
    @pyqtSlot()
    def _poll_read(self):
        try:
            # Auto-reconnect: gerekirse bağlantıları aç
            if hasattr(self.main, "ensure_open"): self.main.ensure_open()
            if hasattr(self.payload, "ensure_open"): self.payload.ensure_open()
            if hasattr(self.ins, "ensure_open"): self.ins.ensure_open()

            # ANA
            if hasattr(self.main, "read_packet_non_blocking") and self.main.read_packet_non_blocking(self.main_size):
                # packet2 buffer'dan okunur (6..n-? arası payload, protokol senin koduna göre)
                pkt = bytes(self.main.packet2[:self.main_size])
                self._last_main = pkt
                self.main_packet.emit(pkt)

            # GÖREV
            if hasattr(self.payload, "read_packet_non_blocking") and self.payload.read_packet_non_blocking(self.payload_size):
                pkt = bytes(self.payload.packet2[:self.payload_size])
                self._last_payload = pkt
                self.payload_pkt.emit(pkt)

            # INS (opsiyonel)
            if hasattr(self.ins, "read_packet_non_blocking") and self.ins.read_packet_non_blocking(self.ins_size):
                pkt = bytes(self.ins.packet2[:self.ins_size])
                self.ins_packet.emit(pkt)

        except Exception as e:
            self.error.emit(f"read: {e}")

    # ---- Gönderim ----
    @pyqtSlot()
    def _tick_send(self):
        # Elimizde son ANA + GÖREV yoksa gönderme
        if self._last_main is None or self._last_payload is None:
            self._last_main = [0] * 84
            self._last_payload = [0] * 35
        try:
            # Paket oluştur
            from core.packet_builder import build_combined_packet
            data = build_combined_packet(self._last_main, self._last_payload, self.counter)
            # HAKEM'e gönder
            if hasattr(self.judge, "ensure_open"): self.judge.ensure_open()
            if hasattr(self.judge, "send_data"):
                self.judge.send_data(data)

            # sayacı çevir
            self.counter = (self.counter + 1) & 0xFF
        except Exception as e:
            self.error.emit(f"send: {e}")
