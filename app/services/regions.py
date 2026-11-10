"""동 이름 비교

가구 프로필의 동은 백엔드 지역 목록의 행정동(예: 상현3동, 동백1동, 양지읍)이고,
시설 데이터의 동은 주소에 적힌 법정동(예: 상현동, 동백동, 양지면)이라 이름이 다를 수 있다.
숫자와 읍·면·동 접미사를 떼고 비교한다. (언남동→구성동처럼 이름이 전혀 다른 경우는 같은 구로만 판단)
"""

import re


def dong_stem(name):
    """'상현3동' → '상현', '동백동' → '동백', '양지면' → '양지'"""
    if not name:
        return None
    stem = re.sub(r"\d+(?=[동읍면]$)", "", name.strip())
    return re.sub(r"[동읍면]$", "", stem) or None


def same_dong(a, b):
    sa, sb = dong_stem(a), dong_stem(b)
    return sa is not None and sa == sb
