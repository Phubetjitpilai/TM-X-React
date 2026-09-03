from decimal import Decimal

def _within_tolerance_decimal(value: float, nominal: float, upper_tol: float, lower_tol: float) -> bool:
    # แปลงเป็น string ก่อน แล้วแปลงเป็น Decimal
    v = Decimal(str(value))
    n = Decimal(str(nominal))
    u = Decimal(str(upper_tol))
    l = Decimal(str(lower_tol))
    
    # คำนวณตรงๆ เหมือนเขียนบนกระดาษ
    return (n - l) <= v <= (n + u)

print(_within_tolerance_decimal(8.05, 8.03, 0.02, 0.01))  # คืนค่า True แน่นอน