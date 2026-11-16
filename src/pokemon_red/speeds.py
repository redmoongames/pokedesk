"""Physical speed shortcuts plus arbitrary finite, nonnegative custom rates."""
import math

SPEED_KEYS = dict(zip('0123456789', (0, 1, 2, 3, 4, 6, 8, 12, 16, 20)))
SPEEDS = tuple(SPEED_KEYS.values())
RUNNING_SPEEDS = SPEEDS[1:]


def normalize_speed(value, *, allow_pause=True):
    if type(value) not in (int,float):
        raise ValueError('Скорость: конечное число от 0; например 0.5, 1.5 или 12')
    try:valid=math.isfinite(value) and (value>=0 if allow_pause else value>0)
    except OverflowError:valid=False
    if not valid:
        raise ValueError('Скорость: конечное число от 0' if allow_pause else 'Рабочая скорость должна быть больше 0')
    return int(value) if value == int(value) else value


def parse_speed(text):
    try:value=float(str(text).strip().replace(',','.').removesuffix('×').strip())
    except ValueError:raise ValueError('Введи скорость числом, например 0,5 или 2,75') from None
    return normalize_speed(value)


def speed_text(value):
    return format(value,'g')
