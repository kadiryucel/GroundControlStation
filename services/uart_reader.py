import serial
import time

class SerialController:
    def __init__(self, port, baudrate, timeout,_size):
        self.comm = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

        # paket okuma state
        self._size = _size
        self.packet = [0] * _size
        self.packet2 = [0] * _size
        self.step = 0
        self.index = 0

        # reconnect durumu
        self._desired_port = port
        self._desired_baud = baudrate
        self._desired_timeout = timeout
        self._last_attempt = 0.0
        self._reconnect_interval = 1.5  # saniye

        # ilk bağlantıyı deneyelim
        self._connect()

    # ---- temel bağlantı ----
    def _connect(self):
        try:
            self.ser = serial.Serial(self._desired_port, self._desired_baud, timeout=self._desired_timeout)
            print(f"[Serial] Connected {self._desired_port} @ {self._desired_baud}")
        except Exception as e:
            self.ser = None
            print(f"[Serial] Connect failed {self._desired_port}: {e}")

    def open(self, port=None, baudrate=None, timeout=None):
        if port: self._desired_port = port
        if baudrate: self._desired_baud = baudrate
        if timeout is not None: self._desired_timeout = timeout
        self.close()
        self._connect()
        return self.is_open

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    @property
    def is_open(self):
        return bool(self.ser and self.ser.is_open)
    
    # ---- otomatik yeniden bağlanma ----
    def ensure_open(self):
        """Kopuksa belirli aralıklarla yeniden dener; açık ise True döner."""
        if self.is_open:
            return True
        now = time.time()
        if (now - self._last_attempt) >= self._reconnect_interval:
            self._last_attempt = now
            self._connect()
        return self.is_open
    
    def _is_connected(self):
        return self.ser and self.ser.is_open

    def read_packet_non_blocking(self,size):
        if not self._is_connected():
            return False
        try:
            while self.ser.in_waiting > 0:
                raw = self.ser.read(1)
                if not raw:
                    break  # timeout, veri yok
                b = raw[0]  # Python 3: bytes[0] zaten int döner
                if self.step == 0 and b == 0xFF:
                    self.step = 1
                    
                elif self.step == 1:
                    if b == 0xFF:
                        self.packet[0:2] = [0xFF, 0xFF]
                        self.index = 2
                        self.step = 2
                    else:
                        self.step = 0
                elif self.step == 2:
                    self.packet[self.index] = b
                    self.index += 1
                    
                    if self.index == self._size:
                        if self.packet[self._size-2] == 0x0D and self.packet[self._size-1] == 0x0A:
                            if self.checksum(5,self._size-3) == self.packet[self._size-3]:
                                self.step = 0
                                self.index = 0
                                self.packet2 = self.packet[:]  # kopya, referans değil
                                return True
                            else:
                                print("checksum error")
                                print("received: {}  calculated: {}".format(self.packet[self._size-3], self.checksum(5, self._size-3)))
        
                            
                        self.step = 0
                        self.index = 0
            # print()
            return False
        except (serial.SerialException, OSError) as e:
            print(f"Serial error: {e}")
            self.step = 0
            self.index = 0
            try:
                if self.ser:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None
            return False

    def checksum(self,x,y):
        return sum(self.packet[x:y]) % 256

class HYISerial:
    def __init__(self, port, baudrate, timeout):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.is_connected = False

        self._desired_port = port
        self._desired_baud = baudrate
        self._desired_timeout = timeout
        self._last_attempt = 0.0
        self._reconnect_interval = 2.0

        self.connect()

    def connect(self):
        try:
            self.ser = serial.Serial(self._desired_port, self._desired_baud, timeout=self._desired_timeout)
            self.is_connected = True
            print(f"[HYI] Connected {self._desired_port} @ {self._desired_baud}")
        except Exception as e:
            self.ser = None
            self.is_connected = False
            print(f"[HYI] Connect failed {self._desired_port}: {e}")

    def disconnect(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.is_connected = False

    def open(self, port=None, baudrate=None, timeout=None):
        if port: self._desired_port = port
        if baudrate: self._desired_baud = baudrate
        if timeout is not None: self._desired_timeout = timeout
        self.disconnect()
        self.connect()
        return self.is_connected

    def ensure_open(self):
        if self.is_connected and self.ser and self.ser.is_open:
            return True
        now = time.time()
        if (now - self._last_attempt) >= self._reconnect_interval:
            self._last_attempt = now
            self.connect()
        return self.is_connected

    def send_data(self, data: bytes):
        if not self.is_connected or not self.ser:
            return False
        try:
            self.ser.write(data)
            self.ser.flush()
            return True
        except (serial.SerialException, OSError) as e:
            print(f"[HYI] Send error on {self._desired_port}: {e}")
            self.disconnect()
            return False