"""Праздники NRW, особые дни и Verkaufsoffene Sonntage Дюссельдорфа."""
from datetime import date, timedelta


def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def holidays_nrw(y):
    """Официальные выходные дни в NRW: магазины закрыты."""
    e = easter(y)
    return {
        date(y, 1, 1): "Новый год",
        e - timedelta(days=2): "Страстная пятница (Karfreitag)",
        e + timedelta(days=1): "Пасхальный понедельник (Ostermontag)",
        date(y, 5, 1): "День труда",
        e + timedelta(days=39): "Вознесение (Christi Himmelfahrt)",
        e + timedelta(days=50): "Духов день (Pfingstmontag)",
        e + timedelta(days=60): "Праздник Тела Христова (Fronleichnam)",
        date(y, 10, 3): "День германского единства",
        date(y, 11, 1): "День всех святых (Allerheiligen)",
        date(y, 12, 25): "Рождество",
        date(y, 12, 26): "Второй день Рождества",
    }


def special_days(y):
    """Не выходные, но жизнь в городе меняется."""
    e = easter(y)
    return {
        e - timedelta(days=52): "Altweiberfastnacht: в 11:11 начинается уличный карнавал, многие офисы закрываются после обеда",
        e - timedelta(days=48): "Rosenmontag: большой карнавальный парад, многие магазины и офисы закрыты, в центре перекрытия",
        date(y, 12, 24): "Сочельник: магазины работают примерно до 14:00",
        date(y, 12, 31): "Канун Нового года: магазины работают примерно до 14:00",
        date(y, 11, 11): "11.11 в 11:11 — открытие карнавального сезона, в Альтштадте многолюдно",
    }


# Город: «под вопросом окончательного разрешения». Источник: t-online, Stadt Düsseldorf. Обновлять каждый год.
SHOPPING_SUNDAYS = {
    date(2026, 11, 29): "Innenstadt (рождественские рынки)",
    date(2026, 12, 6): "Benrath, Eller, Kaiserswerth, Oberkassel, Pempelfort, Derendorf",
}
SHOPPING_HOURS = "13:00–18:00"


def notices(day):
    """Уведомления для утренних сторис на дату day (самые важные первыми)."""
    out = []
    h = {**holidays_nrw(day.year), **holidays_nrw(day.year + 1)}
    sp = {**special_days(day.year), **special_days(day.year + 1)}
    if day in h:
        out.append(f"Сегодня праздник: {h[day]}. Магазины закрыты")
    for n, word in ((1, "Завтра"), (2, "Послезавтра")):
        d = day + timedelta(days=n)
        if d in h:
            out.append(f"{word}, {d:%d.%m} — {h[d]}: магазины закрыты. Закупитесь заранее")
            break
    if day in SHOPPING_SUNDAYS:
        out.append(f"Сегодня Verkaufsoffener Sonntag: магазины открыты {SHOPPING_HOURS} — {SHOPPING_SUNDAYS[day]}")
    elif day + timedelta(days=1) in SHOPPING_SUNDAYS:
        out.append(f"Завтра Verkaufsoffener Sonntag: магазины открыты {SHOPPING_HOURS} — {SHOPPING_SUNDAYS[day + timedelta(days=1)]}")
    if day in sp:
        out.append(sp[day])
    elif day + timedelta(days=1) in sp:
        out.append("Завтра — " + sp[day + timedelta(days=1)])
    return out
