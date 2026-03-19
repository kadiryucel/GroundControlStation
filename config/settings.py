def get_serial_config():
    return {
        "ANA":    {"port": "COM5", "baudrate": 9600, "timeout": 0.1,"_size":84},
        "GOREV":  {"port": "COM6", "baudrate": 9600, "timeout": 0.1,"_size":35},
        "INS":    {"port": "COM7", "baudrate": 9600, "timeout": 0.1,"_size":37},
        "HAKEM":  {"port": "COM8", "baudrate": 19200, "timeout": 0.1},
    }
