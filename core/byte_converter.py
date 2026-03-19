import struct
from typing import List, Union


class ByteConverter:
    """
    Integer ve float değerleri 4 byte'a dönüştürme ve geri çevirme işlemleri
    """

    @staticmethod
    def int_to_4bytes(value: int, byte_order: str = 'little', signed: bool = True) -> bytes:
        if signed:
            if not (-2**31 <= value <= 2**31 - 1):
                raise ValueError(f"Değer {value} işaretli 32-bit integer aralığında değil")
            format_char = '<i' if byte_order == 'little' else '>i'
        else:
            if not (0 <= value <= 2**32 - 1):
                raise ValueError(f"Değer {value} işaretsiz 32-bit integer aralığında değil")
            format_char = '<I' if byte_order == 'little' else '>I'

        return struct.pack(format_char, value)

    @staticmethod
    def bytes_to_int(data: bytes, byte_order: str = 'little', signed: bool = True) -> int:
        if len(data) != 4:
            raise ValueError(f"Veri {len(data)} byte, tam olarak 4 byte olmalı")
        format_char = '<i' if byte_order == 'little' else '>i' if signed else '<I' if byte_order == 'little' else '>I'
        return struct.unpack(format_char, data)[0]

    @staticmethod
    def float_to_4bytes(value: float, byte_order: str = 'little') -> bytes:
        format_char = '<f' if byte_order == 'little' else '>f'
        return struct.pack(format_char, value)

    @staticmethod
    def bytes_to_float(data: bytes, byte_order: str = 'little') -> float:
        if len(data) != 4:
            raise ValueError(f"Veri {len(data)} byte, tam olarak 4 byte olmalı")
        format_char = '<f' if byte_order == 'little' else '>f'
        return struct.unpack(format_char, data)[0]

    @staticmethod
    def number_list_to_bytes(values: List[Union[int, float]], byte_order: str = 'little',
                             signed: bool = True, force_float: bool = False) -> bytes:
        result = b''
        for value in values:
            if force_float or isinstance(value, float):
                result += ByteConverter.float_to_4bytes(value, byte_order)
            else:
                result += ByteConverter.int_to_4bytes(value, byte_order, signed)
        return result

    @staticmethod
    def bytes_to_number_list(data: bytes, byte_order: str = 'little',
                             signed: bool = True, as_float: bool = False) -> List[Union[int, float]]:
        if len(data) % 4 != 0:
            raise ValueError(f"Veri uzunluğu {len(data)} byte, 4'ün katı olmalı")

        result = []
        for i in range(0, len(data), 4):
            chunk = data[i:i + 4]
            if as_float:
                result.append(ByteConverter.bytes_to_float(chunk, byte_order))
            else:
                result.append(ByteConverter.bytes_to_int(chunk, byte_order, signed))
        return result

    @staticmethod
    def int_list_to_bytes(values: List[int], byte_order: str = 'little', signed: bool = True) -> bytes:
        return b''.join(ByteConverter.int_to_4bytes(val, byte_order, signed) for val in values)

    @staticmethod
    def bytes_to_int_list(data: bytes, byte_order: str = 'little', signed: bool = True) -> List[int]:
        if len(data) % 4 != 0:
            raise ValueError("Veri uzunluğu 4'ün katı olmalı")
        return [ByteConverter.bytes_to_int(data[i:i+4], byte_order, signed) for i in range(0, len(data), 4)]

    @staticmethod
    def float_list_to_bytes(values: List[float], byte_order: str = 'little') -> bytes:
        return b''.join(ByteConverter.float_to_4bytes(val, byte_order) for val in values)

    @staticmethod
    def bytes_to_float_list(data: bytes, byte_order: str = 'little') -> List[float]:
        if len(data) % 4 != 0:
            raise ValueError("Veri uzunluğu 4'ün katı olmalı")
        return [ByteConverter.bytes_to_float(data[i:i+4], byte_order) for i in range(0, len(data), 4)]

    @staticmethod
    def show_bytes_hex(data: Union[bytes, List[int]]) -> str:
        if isinstance(data, list):
            data = bytes(data)
        return ' '.join(f'{b:02X}' for b in data)

    @staticmethod
    def check_sum(data: List[int], start: int = 4, end: int = 75) -> int:
        """data[start:end] arasındaki byte'ların toplamı mod 256"""
        return sum(data[start:end]) % 256
