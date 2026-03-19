# core/packet_builder.py
# Kombine paket oluşturucu: ANA + GÖREV'ten alanları harmanlar, checksum ekler.
from core.byte_converter import ByteConverter

# --- Outgoing packet protocol sabitleri ---
SYNC  = [0xFF, 0xFF]
HDR   = [0x54, 0x52, 0x74]     # 'T', 'R', 't'
PKT_SIZE       = 78
IDX_CHECKSUM   = 75            # checksum byte pozisyonu
IDX_TERM       = 76            # 0x0D, 0x0A başlangıcı
CHK_START      = 4             # checksum hesaplama başlangıcı (inclusive)
CHK_END        = 75            # checksum hesaplama bitişi (exclusive)

def build_combined_packet(ana_pkt, gorev_pkt, counter=0):
    data = [0] * PKT_SIZE
    data[0:2] = SYNC
    data[2:5] = HDR
    data[5]   = counter & 0xFF         # yer istasyonu gönderim sayacı

    data[6:22]  = ana_pkt[6:22]
    data[22:34] = gorev_pkt[6:18]
    data[34:46] = [0] * 12
    data[46:70] = ana_pkt[22:46]
    data[70:74] = ana_pkt[50:54]
    data[74]    = ana_pkt[80]

    data[IDX_CHECKSUM] = ByteConverter.check_sum(data, CHK_START, CHK_END)
    data[IDX_TERM:IDX_TERM + 2] = [0x0D, 0x0A]
    return data