"""Printable A4 tab sheet: header with key/tempo/tuning, six-line TAB staves
with fret numbers on the strings, bend arrows, bar numbers, video timestamps."""
from datetime import date

from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from tab_core import STRING_NAMES, fmt_time

PAGE_W, PAGE_H = A4
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 40, 44, 46
CONTENT_W = PAGE_W - 2 * MARGIN_X
BARS_PER_SYSTEM = 3
STRING_GAP = 7.2
STAFF_H = STRING_GAP * 5
CLEF_W = 20
ABOVE_STAFF = 20  # room for bend arrows and their labels
SYSTEM_H = ABOVE_STAFF + STAFF_H + 22  # + bar number/time line under the staff
HEADER_H = 96
FRET_FONT, FRET_SIZE = "Helvetica-Bold", 7.6
GREY = Color(0.45, 0.45, 0.45)
LIGHT = Color(0.55, 0.55, 0.55)


def _slots(tab):
    """Bars to draw. Runs of 2+ empty bars collapse into one rest slot."""
    slots, i = [], 0
    while i < len(tab.bars):
        j = i
        while j < len(tab.bars) and not tab.bars[j].cells:
            j += 1
        if j - i >= 2:
            slots.append(("rest", i + 1, tab.bars[i].time, j - i))
            i = j
        else:
            slots.append(("bar", i + 1, tab.bars[i].time, tab.bars[i]))
            i += 1
    return slots


def _paginate(n_systems):
    first = int((PAGE_H - MARGIN_TOP - MARGIN_BOTTOM - HEADER_H) // SYSTEM_H)
    rest = int((PAGE_H - MARGIN_TOP - MARGIN_BOTTOM) // SYSTEM_H)
    pages, i = [], 0
    while i < n_systems or not pages:
        take = first if not pages else rest
        pages.append(range(i, min(i + take, n_systems)))
        i += take
    return pages


def _header(c, tab, title, subtitle, source):
    y = PAGE_H - MARGIN_TOP - 16
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(MARGIN_X, y, title[:70])
    y -= 17
    c.setFont("Helvetica", 10)
    c.setFillColor(GREY)
    if subtitle:
        c.drawString(MARGIN_X, y, subtitle)
        y -= 13
    if source:
        c.setFont("Helvetica", 8)
        c.drawString(MARGIN_X, y, source[:110])
        c.linkURL(source, (MARGIN_X, y - 2, MARGIN_X + stringWidth(source[:110], "Helvetica", 8), y + 8))
        y -= 18
    else:
        y -= 5
    c.setFillColor(black)
    items = [("Tuning", "E A D G B E (standard)"), ("Key", f"{tab.key} (estimated)"),
             ("Tempo", f"~{tab.tempo:.0f} BPM" if tab.tempo else "?"), ("Time", "4/4")]
    x = MARGIN_X
    for label, value in items:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x, y, label + ":")
        x += stringWidth(label + ": ", "Helvetica-Bold", 9)
        c.setFont("Helvetica", 9)
        c.drawString(x, y, value)
        x += stringWidth(value, "Helvetica", 9) + 18
    y -= 10
    c.setStrokeColor(LIGHT)
    c.setLineWidth(0.6)
    c.line(MARGIN_X, y, PAGE_W - MARGIN_X, y)


def _footer(c, page, total):
    c.setFont("Helvetica", 7.5)
    c.setFillColor(GREY)
    c.drawString(MARGIN_X, MARGIN_BOTTOM - 22,
                 f"Automatic transcription, a draft to check by ear. Arrows = bends; bar number • video time under each bar. "
                 f"Generated {date.today():%Y-%m-%d}.")
    c.drawRightString(PAGE_W - MARGIN_X, MARGIN_BOTTOM - 22, f"Page {page} of {total}")
    c.setFillColor(black)


def _bend_arrow(c, x, y_note, y_top, amount):
    """Curved arrow from a fret number up above the staff, labelled ½ or full."""
    c.setStrokeColor(black)
    c.setLineWidth(0.7)
    p = c.beginPath()
    p.moveTo(x, y_note)
    p.curveTo(x + 5, y_note, x + 6, y_note + 4, x + 6, y_top - 3)
    c.drawPath(p, stroke=1, fill=0)
    tip = c.beginPath()
    tip.moveTo(x + 6, y_top)
    tip.lineTo(x + 4.3, y_top - 3.6)
    tip.lineTo(x + 7.7, y_top - 3.6)
    tip.close()
    c.setFillColor(black)
    c.drawPath(tip, stroke=0, fill=1)
    c.setFont("Helvetica", 6)
    c.drawCentredString(x + 6, y_top + 1.5, "full" if amount >= 2 else "½")


def _system(c, tab, slots, top, show_clef=True):
    staff_top = top - ABOVE_STAFF
    staff_bot = staff_top - STAFF_H
    x0 = MARGIN_X + CLEF_W
    bar_w = (CONTENT_W - CLEF_W) / BARS_PER_SYSTEM
    x_end = x0 + bar_w * len(slots)

    c.setStrokeColor(black)
    c.setLineWidth(0.45)
    for s in range(6):
        y = staff_top - s * STRING_GAP
        c.line(MARGIN_X, y, x_end, y)
    c.setLineWidth(0.9)
    c.line(MARGIN_X, staff_top, MARGIN_X, staff_bot)

    # TAB clef, on a white patch so the string lines don't run through the letters
    mid = (staff_top + staff_bot) / 2
    c.setFillColor(white)
    c.rect(MARGIN_X + 3, staff_bot + 1.5, 12, STAFF_H - 3, stroke=0, fill=1)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 10)
    for i, ch in enumerate("TAB"):
        c.drawCentredString(MARGIN_X + 9, mid + 7.5 - i * 11, ch)
    if show_clef:
        c.setFont("Helvetica", 5.5)
        c.setFillColor(GREY)
        for s, name in enumerate(STRING_NAMES):
            c.drawRightString(MARGIN_X - 3, staff_top - s * STRING_GAP - 2, name)
        c.setFillColor(black)

    pad = 6
    step_w = (bar_w - 2 * pad) / tab.steps_per_bar
    for i, slot in enumerate(slots):
        kind, number, t = slot[0], slot[1], slot[2]
        bx = x0 + i * bar_w
        c.setLineWidth(0.7)
        c.line(bx + bar_w, staff_top, bx + bar_w, staff_bot)
        # bar number and video time sit under the staff, clear of bend arrows
        c.setFont("Helvetica-Oblique", 6.8)
        c.setFillColor(GREY)
        c.drawString(bx + 2, staff_bot - 9, str(number))
        c.setFont("Helvetica", 6.5)
        c.drawString(bx + 4 + stringWidth(str(number), "Helvetica-Oblique", 6.8), staff_bot - 9,
                     f"• {fmt_time(t)}")
        c.setFillColor(black)

        if kind == "rest":
            c.setFont("Helvetica-Oblique", 8)
            c.setFillColor(white)
            label = f"{slot[3]} bars rest"
            w = stringWidth(label, "Helvetica-Oblique", 8) + 8
            c.rect(bx + bar_w / 2 - w / 2, mid - 5, w, 10, stroke=0, fill=1)
            c.setFillColor(GREY)
            c.drawCentredString(bx + bar_w / 2, mid - 2.8, label)
            c.setFillColor(black)
            continue

        bar = slot[3]
        for k, strings in sorted(bar.cells.items()):
            x = bx + pad + (k + 0.5) * step_w
            for s, (fret, bend) in strings.items():
                y = staff_top - s * STRING_GAP
                txt = str(fret)
                w = stringWidth(txt, FRET_FONT, FRET_SIZE)
                c.setFillColor(white)
                c.rect(x - w / 2 - 1, y - 3.4, w + 2, 6.8, stroke=0, fill=1)
                c.setFillColor(black)
                c.setFont(FRET_FONT, FRET_SIZE)
                c.drawCentredString(x, y - 2.7, txt)
                if bend:
                    _bend_arrow(c, x + w / 2 + 0.8, y + 0.5, staff_top + 10, bend)


def write_pdf(tab, path, title, subtitle=None, source=None):
    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle(title)
    c.setAuthor("Guitar Tabber")
    c.setSubject("Guitar tab (automatic transcription)")

    slots = _slots(tab)
    systems = [slots[i:i + BARS_PER_SYSTEM] for i in range(0, len(slots), BARS_PER_SYSTEM)]
    pages = _paginate(len(systems))
    for p, idx in enumerate(pages):
        top = PAGE_H - MARGIN_TOP
        if p == 0:
            _header(c, tab, title, subtitle, source)
            top -= HEADER_H
            if not systems:
                c.setFont("Helvetica", 11)
                c.drawString(MARGIN_X, top - 20, "No lead guitar notes were detected in this section.")
        for n, si in enumerate(idx):
            _system(c, tab, systems[si], top - n * SYSTEM_H)
        _footer(c, p + 1, len(pages))
        c.showPage()
    c.save()
    return path
