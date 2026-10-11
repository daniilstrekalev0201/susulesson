"""Сборка конспектов в PDF по СТО ЮУрГУ 04–2008 (запускается на компьютере, не на сервере).

    python konspekty/build.py            — собрать все лекции konspekty/src/<предмет>/NN.txt
    python konspekty/build.py em         — только предмет src/em/
Результат: konspekty/pdf/<предмет>/NN.pdf и konspekty/pdf/index.json (его читает бот).

Оформление по СТО ЮУрГУ 04–2008, п. 4: А4; поля: левое 25 мм, правое 10 мм, верхнее и нижнее 20 мм;
Times New Roman 14 пт, одинарный интервал, абзацный отступ 0,7 см; рамка и основная надпись
по ГОСТ 2.104 (форма 2 на первом листе после титульного, форма 2а на остальных); разделы 1, 2 …
прописными, подразделы 1.1 …; «Выводы по разделу …» в конце каждого раздела; формулы на отдельной
строке с номером (1.1) справа и пояснением «где …»; таблицы «Таблица 1.1 – …»; сквозная нумерация
листов, титульный лист не нумеруется.

Разметка исходника (src/*.txt):
    src/<предмет>/_subject.txt: @subject, @teacher, @dept, @code_base, @order, @sources (общие для лекций)
    src/<предмет>/NN.txt: @lecture N, @title Тема лекции, при необходимости свои @sources
    = ЗАГОЛОВОК           — ненумерованный раздел (ВВЕДЕНИЕ)
    # Заголовок           — раздел 1, 2 …
    ## Заголовок          — подраздел 1.1 …
    обычный текст         — абзац (пустая строка — конец абзаца)
    - пункт               — перечисление с тире
    $ формула             — формула с номером; следующие строки «| …» — пояснение «где …»
    > вывод               — пункт «Выводов по разделу»
    %table Название       — таблица, дальше строки «a | b | c» до пустой строки (первая — шапка)
    Внутри строк: X_{1} — нижний индекс, X^{2} — верхний, **жирный**, *курсив*.
"""

import json
import os
import re
import sys
from html import escape

from fontTools.ttLib import TTFont as FontFile

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
for name, file in [("TNR", "times.ttf"), ("TNR-B", "timesbd.ttf"), ("TNR-I", "timesi.ttf"),
                   ("TNR-BI", "timesbi.ttf")]:
    pdfmetrics.registerFont(TTFont(name, os.path.join(FONTS, file)))
pdfmetrics.registerFontFamily("TNR", normal="TNR", bold="TNR-B", italic="TNR-I", boldItalic="TNR-BI")
# Запасной шрифт для математических знаков, которых нет в Times New Roman (⊕, ∈, ∮ …).
pdfmetrics.registerFont(TTFont("SYM", os.path.join(FONTS, "seguisym.ttf")))
TNR_CHARS = set(FontFile(os.path.join(FONTS, "times.ttf")).getBestCmap())
SYM_CHARS = set(FontFile(os.path.join(FONTS, "seguisym.ttf")).getBestCmap())

PAGE_W, PAGE_H = A4
SIZE = 14
LEAD = 16.1  # «одинарный» интервал Word для Times New Roman 14 пт
INDENT = 7 * mm

# Поля по СТО: левое 25, правое 10, верх/низ 20 мм. Внизу ещё основная надпись (15 или 40 мм от рамки 5 мм).
LEFT, RIGHT, TOP = 25 * mm, 10 * mm, 20 * mm
BOTTOM_2A = 5 * mm + 15 * mm + 5 * mm
BOTTOM_2 = 5 * mm + 40 * mm + 5 * mm

ST = {
    "body": ParagraphStyle("body", fontName="TNR", fontSize=SIZE, leading=LEAD, firstLineIndent=INDENT,
                           alignment=TA_JUSTIFY),
    "item": ParagraphStyle("item", fontName="TNR", fontSize=SIZE, leading=LEAD, firstLineIndent=INDENT,
                           alignment=TA_JUSTIFY),
    "h1": ParagraphStyle("h1", fontName="TNR-B", fontSize=SIZE, leading=LEAD, firstLineIndent=INDENT,
                         spaceBefore=LEAD, spaceAfter=LEAD, alignment=TA_LEFT),
    "h1c": ParagraphStyle("h1c", fontName="TNR-B", fontSize=SIZE, leading=LEAD, alignment=TA_CENTER,
                          spaceAfter=LEAD),
    "h2": ParagraphStyle("h2", fontName="TNR-B", fontSize=SIZE, leading=LEAD, firstLineIndent=INDENT,
                         spaceBefore=LEAD, spaceAfter=LEAD / 2, alignment=TA_LEFT),
    "concl": ParagraphStyle("concl", fontName="TNR-B", fontSize=SIZE, leading=LEAD, firstLineIndent=INDENT,
                            spaceBefore=LEAD, spaceAfter=LEAD / 2),
    "formula": ParagraphStyle("formula", fontName="TNR", fontSize=SIZE, leading=LEAD + 2, alignment=TA_CENTER),
    "where": ParagraphStyle("where", fontName="TNR", fontSize=SIZE, leading=LEAD, leftIndent=0),
    "where2": ParagraphStyle("where2", fontName="TNR", fontSize=SIZE, leading=LEAD, leftIndent=12 * mm),
    "tcap": ParagraphStyle("tcap", fontName="TNR", fontSize=SIZE, leading=LEAD, spaceBefore=LEAD / 2,
                           spaceAfter=3),
    "cell": ParagraphStyle("cell", fontName="TNR", fontSize=12, leading=13.8),
    "cellh": ParagraphStyle("cellh", fontName="TNR", fontSize=12, leading=13.8, alignment=TA_CENTER),
    "src": ParagraphStyle("src", fontName="TNR", fontSize=SIZE, leading=LEAD, firstLineIndent=INDENT,
                          alignment=TA_JUSTIFY, spaceAfter=2),
    "toc1": ParagraphStyle("toc1", fontName="TNR", fontSize=SIZE, leading=LEAD),
    "toc2": ParagraphStyle("toc2", fontName="TNR", fontSize=SIZE, leading=LEAD, leftIndent=7 * mm),
    "tp": ParagraphStyle("tp", fontName="TNR", fontSize=SIZE, leading=LEAD, alignment=TA_CENTER),
    "tpb": ParagraphStyle("tpb", fontName="TNR-B", fontSize=16, leading=20, alignment=TA_CENTER),
    "tpr": ParagraphStyle("tpr", fontName="TNR", fontSize=SIZE, leading=LEAD, leftIndent=95 * mm),
}

NUM_WORDS = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять",
             "одиннадцать", "двенадцать"]


def inline(text: str) -> str:
    """Безопасный HTML для Paragraph: индексы, жирный, курсив."""
    s = escape(text, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*{])\*(?![\s}])([^<>*{}]+?)(?<!\s)\*(?![\w*}])", r"<i>\1</i>", s)
    s = re.sub(r"_\{(.+?)\}", r'<sub size="10" rise="3">\1</sub>', s)
    s = re.sub(r"\^\{(.+?)\}", r'<super size="10" rise="5">\1</super>', s)
    return "".join(f'<font name="SYM">{ch}</font>' if ord(ch) > 127 and ord(ch) not in TNR_CHARS
                   and ord(ch) in SYM_CHARS else ch for ch in s)


# ---------- основная надпись ----------

def _cell(c, x, y, w, h, text="", size=7, font="TNR-I", align="c"):
    if text:
        c.setFont(font, size)
        ty = y + (h - size * 0.7) / 2
        if align == "c":
            c.drawCentredString(x + w / 2, ty, text)
        else:
            c.drawString(x + 1 * mm, ty, text)


def _fit(c, text, font, size, width):
    while size > 5 and c.stringWidth(text, font, size) > width:
        size -= 0.5
    return size


def draw_frame(c, doc, big: bool):
    c.saveState()
    c.setLineWidth(0.8)
    x0, y0 = 20 * mm, 5 * mm
    c.rect(x0, y0, PAGE_W - 25 * mm, PAGE_H - 10 * mm)
    cols = [7, 10, 23, 15, 10]
    xs = [x0]
    for w in cols:
        xs.append(xs[-1] + w * mm)
    lw = 0.8
    meta = doc.meta
    page = c.getPageNumber()
    if not big:  # форма 2а: 185 × 15 мм
        h = 15 * mm
        c.rect(x0, y0, 185 * mm, h)
        for x in xs[1:]:
            c.line(x, y0, x, y0 + h)
        for r in (1, 2):
            c.setLineWidth(0.3 if r < 2 else lw)
            c.line(x0, y0 + r * 5 * mm, xs[-1], y0 + r * 5 * mm)
        c.setLineWidth(lw)
        for x, w, t in zip(xs, cols, ["Изм.", "Лист", "№ докум.", "Подп.", "Дата"]):
            _cell(c, x, y0, w * mm, 5 * mm, t)
        xr = x0 + 175 * mm
        c.line(xr, y0, xr, y0 + h)
        c.line(xr, y0 + 8 * mm, x0 + 185 * mm, y0 + 8 * mm)
        _cell(c, xr, y0 + 8 * mm, 10 * mm, 7 * mm, "Лист", 7)
        _cell(c, xr, y0, 10 * mm, 8 * mm, str(page), 10, "TNR")
        size = _fit(c, meta["code"], "TNR-I", 14, 105 * mm)
        _cell(c, xs[-1], y0, 110 * mm, h, meta["code"], size)
    else:  # форма 2: 185 × 40 мм
        h = 40 * mm
        c.rect(x0, y0, 185 * mm, h)
        top = y0 + h
        # левый блок 65 мм × 8 строк по 5 мм
        for r in range(1, 8):
            yy = top - r * 5 * mm
            c.setLineWidth(lw if r in (2, 3) else 0.3)
            c.line(x0, yy, xs[-1], yy)
        c.setLineWidth(lw)
        for i, x in enumerate(xs[1:]):
            if i == 0:  # граница «Изм.|Лист» — только в верхних трёх строках
                c.line(x, top - 15 * mm, x, top)
            else:
                c.line(x, y0, x, top)
        for x, w, t in zip(xs, cols, ["Изм.", "Лист", "№ докум.", "Подп.", "Дата"]):
            _cell(c, x, top - 15 * mm, w * mm, 5 * mm, t)
        for r, t in enumerate(["Разраб.", "Пров.", "", "Н. контр.", "Утв."]):
            _cell(c, x0, top - (4 + r) * 5 * mm, 17 * mm, 5 * mm, t, 7, align="l")
        for r, t in enumerate([meta.get("author", ""), "", "", "", ""]):
            if t:
                s = _fit(c, t, "TNR-I", 7, 22 * mm)
                _cell(c, xs[2], top - (4 + r) * 5 * mm, 23 * mm, 5 * mm, t, s, align="l")
        # обозначение 120 × 15
        xm = xs[-1]
        c.line(xm, top - 15 * mm, x0 + 185 * mm, top - 15 * mm)
        size = _fit(c, meta["code"], "TNR-I", 14, 115 * mm)
        _cell(c, xm, top - 15 * mm, 120 * mm, 15 * mm, meta["code"], size)
        # наименование 70 × 25
        xn = xm + 70 * mm
        c.line(xn, y0, xn, top - 15 * mm)
        tail = f"Конспект лекции № {meta['lecture']}" if meta.get("lecture") else "Конспект лекций"
        fs = 11
        while True:
            lines = _wrap(c, meta["subject"], "TNR-I", fs, 66 * mm) + [tail]
            if len(lines) * fs * 0.47 * mm <= 23 * mm or fs <= 7:
                break
            fs -= 0.5
        step = fs * 0.47 * mm
        yy = y0 + 12.5 * mm + (len(lines) - 1) * step / 2
        for ln in lines:
            c.setFont("TNR-I", fs)
            c.drawCentredString(xm + 35 * mm, yy - 2, ln)
            yy -= step
        # Лит. / Лист / Листов
        c.line(xn, top - 20 * mm, x0 + 185 * mm, top - 20 * mm)
        c.line(xn, top - 25 * mm, x0 + 185 * mm, top - 25 * mm)
        for dx in (5, 10, 15):
            c.setLineWidth(0.3 if dx in (5, 10) else lw)
            c.line(xn + dx * mm, top - 25 * mm, xn + dx * mm, top - (20 if dx != 15 else 15) * mm)
        c.setLineWidth(lw)
        c.line(xn + 15 * mm, top - 25 * mm, xn + 15 * mm, top - 15 * mm)
        c.line(xn + 30 * mm, top - 25 * mm, xn + 30 * mm, top - 15 * mm)
        _cell(c, xn, top - 20 * mm, 15 * mm, 5 * mm, "Лит.")
        _cell(c, xn + 15 * mm, top - 20 * mm, 15 * mm, 5 * mm, "Лист")
        _cell(c, xn + 30 * mm, top - 20 * mm, 20 * mm, 5 * mm, "Листов")
        _cell(c, xn, top - 25 * mm, 5 * mm, 5 * mm, "У", 9, "TNR")
        _cell(c, xn + 15 * mm, top - 25 * mm, 15 * mm, 5 * mm, str(page), 10, "TNR")
        _cell(c, xn + 30 * mm, top - 25 * mm, 20 * mm, 5 * mm, str(doc.meta.get("pages", "")), 10, "TNR")
        _cell(c, xn, y0 + 7.5 * mm, 50 * mm, 6 * mm, "ЮУрГУ", 11)
        _cell(c, xn, y0 + 2 * mm, 50 * mm, 6 * mm, meta.get("org2", ""), 10)
    c.restoreState()


def _wrap(c, text, font, size, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if c.stringWidth(test, font, size) <= width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


class Doc(BaseDocTemplate):
    def __init__(self, path, meta):
        super().__init__(path, pagesize=A4, title=doc_title(meta),
                         author="Конспект для группы П-377", leftMargin=LEFT, rightMargin=RIGHT,
                         topMargin=TOP, bottomMargin=BOTTOM_2A)
        self.meta = meta
        w = PAGE_W - LEFT - RIGHT
        title_frame = Frame(LEFT, 20 * mm, w, PAGE_H - 40 * mm, id="t", leftPadding=0, rightPadding=0,
                            topPadding=0, bottomPadding=0)
        first = Frame(LEFT, BOTTOM_2, w, PAGE_H - TOP - BOTTOM_2, id="f", leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        rest = Frame(LEFT, BOTTOM_2A, w, PAGE_H - TOP - BOTTOM_2A, id="r", leftPadding=0, rightPadding=0,
                     topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate("title", [title_frame], onPage=self._city),
            PageTemplate("first", [first], onPage=lambda c, d: draw_frame(c, d, True)),
            PageTemplate("rest", [rest], onPage=lambda c, d: draw_frame(c, d, False)),
        ])

    def _city(self, c, doc):
        c.setFont("TNR", SIZE)
        c.drawCentredString(LEFT + (PAGE_W - LEFT - RIGHT) / 2, 22 * mm, self.meta.get("city", "Челябинск 2026"))

    def afterFlowable(self, f):
        level = getattr(f, "_toc_level", None)
        if level is not None:
            self.notify("TOCEntry", (level, f._toc_text, self.page))

    def afterPage(self):
        self.meta["_last"] = self.page


def doc_title(meta):
    if meta.get("lecture"):
        return f"{meta['subject']}. Лекция {meta['lecture']}. {meta['title']}"
    return f"{meta['subject']} — конспект лекций"


def heading(text, style, level, toc_text):
    p = Paragraph(inline(text), ST[style])
    p._toc_level = level
    p._toc_text = escape(toc_text)
    return p


def title_page(meta):
    parts = [
        Paragraph("Министерство науки и высшего образования Российской Федерации", ST["tp"]),
        Paragraph("Федеральное государственное автономное образовательное учреждение высшего образования", ST["tp"]),
        Paragraph("«Южно-Уральский государственный университет", ST["tp"]),
        Paragraph("(национальный исследовательский университет)»", ST["tp"]),
        Paragraph("Политехнический институт", ST["tp"]),
    ]
    if meta.get("dept"):
        parts.append(Paragraph(f"Кафедра «{escape(meta['dept'])}»", ST["tp"]))
    parts += [
        Spacer(1, 50 * mm),
        Paragraph(f"КОНСПЕКТ ЛЕКЦИИ № {meta['lecture']}" if meta.get("lecture") else "КОНСПЕКТ ЛЕКЦИЙ", ST["tpb"]),
        Spacer(1, 4 * mm),
        Paragraph(f"по дисциплине «{escape(meta['subject'])}»", ST["tp"]),
        Spacer(1, 6 * mm),
    ]
    if meta.get("lecture"):
        parts += [Paragraph(escape(meta["title"]), ST["tpb"]), Spacer(1, 6 * mm)]
    parts += [
        Paragraph(escape(meta["code"]), ST["tp"]),
        Spacer(1, 30 * mm),
    ]
    if meta.get("teacher"):
        parts.append(Paragraph(f"Преподаватель: {escape(meta['teacher'])}", ST["tpr"]))
        parts.append(Spacer(1, 3 * mm))
    parts += [Paragraph("Составлен для группы П-377", ST["tpr"]),
              Paragraph("по материалам курса в «Электронном ЮУрГУ»", ST["tpr"]),
              Spacer(1, 1), ]
    return parts


def parse(path):
    meta, body = {"sources": []}, []
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    in_sources = False
    for ln in lines:
        if ln.startswith("@"):
            key, _, val = ln[1:].partition(" ")
            in_sources = key == "sources"
            if not in_sources:
                meta[key] = val.strip()
            continue
        if in_sources:
            if ln.startswith("- "):
                meta["sources"].append(ln[2:].strip())
                continue
            if not ln.strip():
                continue
            in_sources = False
        body.append(ln)
    return meta, body


def story_from(meta, body):
    story = title_page(meta)
    story += [NextPageTemplate("first"), PageBreak(), NextPageTemplate("rest")]
    toc = TableOfContents(levelStyles=[ST["toc1"], ST["toc2"]], dotsMinLevel=0)
    toc.tableStyle = TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)])
    story += [Paragraph("ОГЛАВЛЕНИЕ", ST["h1c"]), toc]
    lecture_mode = bool(meta.get("lecture"))
    story.append(Spacer(1, LEAD) if lecture_mode else PageBreak())

    sec = sub = formula = table = 0
    conclusions: list[str] = []
    para: list[str] = []
    i = 0

    def flush_para():
        if para:
            story.append(Paragraph(inline(" ".join(para)), ST["body"]))
            para.clear()

    def flush_concl():
        if sec and conclusions:
            word = NUM_WORDS[sec] if sec < len(NUM_WORDS) else str(sec)
            story.append(CondPageBreak(4 * LEAD))
            story.append(heading(f"Выводы по разделу {word}", "concl", 1, f"Выводы по разделу {word}"))
            for k, c in enumerate(conclusions, 1):
                story.append(Paragraph(f"{k}) " + inline(c), ST["item"]))
            conclusions.clear()

    while i < len(body):
        ln = body[i].rstrip()
        if not ln.strip():
            flush_para()
        elif ln.startswith("## "):
            flush_para()
            sub += 1
            formula_sec = sec
            text = f"{sec}.{sub} {ln[3:].strip()}"
            story.append(CondPageBreak(5 * LEAD))
            story.append(heading(text, "h2", 1, text))
        elif ln.startswith("# "):
            flush_para()
            flush_concl()
            sec += 1
            sub = formula = table = 0
            text = f"{sec} {ln[2:].strip().upper()}"
            story.append(PageBreak() if sec > 1 and not lecture_mode else Spacer(1, 0))
            story.append(CondPageBreak(6 * LEAD))
            story.append(heading(text, "h1", 0, text))
        elif ln.startswith("= "):
            flush_para()
            text = ln[2:].strip().upper()
            story.append(heading(text, "h1c", 0, text))
        elif ln.startswith("- "):
            flush_para()
            story.append(Paragraph("– " + inline(ln[2:].strip()), ST["item"]))
        elif ln.startswith("> "):
            flush_para()
            conclusions.append(ln[2:].strip())
        elif ln.startswith("$ "):
            flush_para()
            formula += 1
            num = f"({sec}.{formula})" if sec else f"({formula})"
            expr = ln[2:].strip()
            w = PAGE_W - LEFT - RIGHT
            t = Table([[Paragraph(inline(expr), ST["formula"]), Paragraph(num, ST["formula"])]],
                      colWidths=[w - 22 * mm, 22 * mm])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
            block = [Spacer(1, LEAD * 0.6), t]
            expl = []
            while i + 1 < len(body) and body[i + 1].startswith("| "):
                i += 1
                expl.append(body[i][2:].strip())
            for k, e in enumerate(expl):
                block.append(Paragraph(inline(e), ST["where" if k == 0 else "where2"]))
            block.append(Spacer(1, LEAD * 0.6))
            story.append(KeepTogether(block))
        elif ln.startswith("%table"):
            flush_para()
            table += 1
            cap = ln[6:].strip()
            rows = []
            while i + 1 < len(body) and body[i + 1].strip():
                i += 1
                rows.append([c.strip() for c in body[i].split("|")])
            ncol = max(len(r) for r in rows)
            data = [[Paragraph(inline(c), ST["cellh" if r == 0 else "cell"]) for c in row + [""] * (ncol - len(row))]
                    for r, row in enumerate(rows)]
            w = PAGE_W - LEFT - RIGHT
            first_w = w * (0.34 if ncol > 2 else 0.4)
            widths = [first_w] + [(w - first_w) / (ncol - 1)] * (ncol - 1)
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black"),
                                   ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 2),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            num = f"{sec}.{table}" if sec else str(table)
            story.append(KeepTogether([Paragraph(f"Таблица {num} – " + inline(cap), ST["tcap"]), t]))
            story.append(Spacer(1, LEAD / 2))
        else:
            para.append(ln.strip())
        i += 1
    flush_para()
    flush_concl()

    if meta["sources"]:
        story.append(CondPageBreak(8 * LEAD) if lecture_mode else PageBreak())
        story.append(heading("БИБЛИОГРАФИЧЕСКИЙ СПИСОК", "h1c", 0, "БИБЛИОГРАФИЧЕСКИЙ СПИСОК"))
        for k, s in enumerate(meta["sources"], 1):
            story.append(Paragraph(f"{k} " + inline(s), ST["src"]))
    return story


def read_subject(subj):
    meta, _ = parse(os.path.join(HERE, "src", subj, "_subject.txt"))
    return meta


def build(subj, fname, out_dir):
    meta = read_subject(subj)
    common_sources = meta["sources"]
    lmeta, body = parse(os.path.join(HERE, "src", subj, fname))
    meta.update({k: v for k, v in lmeta.items() if k != "sources"})
    meta["sources"] = lmeta["sources"] or common_sources
    if meta.get("lecture"):
        meta["code"] = f"{meta['code_base']}.{int(meta['lecture']):02d} КЛ"
    meta.setdefault("org2", "Группа П-377")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, fname[:-4] + ".pdf")
    meta["pages"] = ""
    Doc(out, meta).multiBuild(story_from(meta, body))
    meta["pages"] = meta["_last"]
    Doc(out, meta).multiBuild(story_from(meta, body))
    print(f"{out}: {meta['pages']} стр.")
    return {"lecture": int(meta.get("lecture", 0)), "title": meta["title"], "file": os.path.basename(out),
            "pages": meta["pages"]}


def build_all(only=None):
    src = os.path.join(HERE, "src")
    index_path = os.path.join(HERE, "pdf", "index.json")
    index = {}
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            index = {s["slug"]: s for s in json.load(f)}
    for subj in sorted(os.listdir(src)):
        if subj.startswith("_") or not os.path.isdir(os.path.join(src, subj)) or (only and subj not in only):
            continue
        meta = read_subject(subj)
        files = sorted(f for f in os.listdir(os.path.join(src, subj)) if f.endswith(".txt") and not f.startswith("_"))
        lectures = [build(subj, f, os.path.join(HERE, "pdf", subj)) for f in files]
        index[subj] = {"slug": subj, "subject": meta["subject"], "order": int(meta.get("order", 99)),
                       "lectures": sorted(lectures, key=lambda x: x["lecture"])}
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(sorted(index.values(), key=lambda s: (s["order"], s["subject"])), f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    build_all(sys.argv[1:] or None)
