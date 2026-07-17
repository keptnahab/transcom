#!/usr/bin/env python3
"""Build the German TransCom beta handbook as a polished A4 PDF."""

from __future__ import annotations

from pathlib import Path
from textwrap import shorten

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle


ROOT = Path(__file__).resolve().parents[2]
# The website always serves this current, CI-consistent handbook - never an
# older beta attachment alongside it.
OUT = ROOT / "beta-website" / "public" / "downloads" / "TransCom_Beta-Handbuch_DE.pdf"
PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
BOTTOM = 16 * mm

INK = colors.HexColor("#1C2F43")
MUTED = colors.HexColor("#68798A")
TEAL = colors.HexColor("#E76522")
TEAL_DARK = colors.HexColor("#153B59")
TEAL_PALE = colors.HexColor("#F6E5DA")
BLUE = colors.HexColor("#2B5F86")
BLUE_PALE = colors.HexColor("#E9F0F5")
AMBER = colors.HexColor("#C94E12")
AMBER_PALE = colors.HexColor("#FBE9DC")
RED = colors.HexColor("#A83A3A")
RED_PALE = colors.HexColor("#FDECEC")
GREEN = colors.HexColor("#217A4A")
GREEN_PALE = colors.HexColor("#EAF6EF")
LINE = colors.HexColor("#DED8CF")
PAPER = colors.HexColor("#F8F6F1")
WHITE = colors.white


FONT_DIR = Path("/System/Library/Fonts/Supplemental")
pdfmetrics.registerFont(TTFont("Arial", str(FONT_DIR / "Arial.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Bold", str(FONT_DIR / "Arial Bold.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Italic", str(FONT_DIR / "Arial Italic.ttf")))
pdfmetrics.registerFont(TTFont("Georgia", str(FONT_DIR / "Georgia.ttf")))
pdfmetrics.registerFont(TTFont("Georgia-Bold", str(FONT_DIR / "Georgia Bold.ttf")))


def style(name: str, **kwargs) -> ParagraphStyle:
    defaults = dict(
        fontName="Arial",
        fontSize=9.2,
        leading=13.1,
        textColor=INK,
        spaceAfter=0,
        spaceBefore=0,
        allowWidows=0,
        allowOrphans=0,
    )
    defaults.update(kwargs)
    return ParagraphStyle(name, **defaults)


S_BODY = style("body")
S_SMALL = style("small", fontSize=8.0, leading=10.8, textColor=MUTED)
S_NOTE = style("note", fontSize=8.7, leading=12.0)
S_H1 = style("h1", fontName="Georgia-Bold", fontSize=22, leading=25, textColor=INK)
S_H2 = style("h2", fontName="Georgia-Bold", fontSize=12.2, leading=15, textColor=TEAL_DARK)
S_STEP = style("step", fontSize=9.1, leading=12.6)
S_CODE = style("code", fontName="Courier", fontSize=7.4, leading=10.0, textColor=INK)
S_TABLE = style("table", fontSize=7.7, leading=10.2)
S_TABLE_HEAD = style("table_head", fontName="Arial-Bold", fontSize=7.7, leading=9.7, textColor=WHITE)


def esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Page:
    def __init__(self, c: canvas.Canvas, number: int, title: str, eyebrow: str = "BETA-HANDBUCH"):
        self.c = c
        self.number = number
        self.y = PAGE_H - 19 * mm
        self._header(title, eyebrow)

    def _header(self, title: str, eyebrow: str) -> None:
        c = self.c
        c.setFillColor(TEAL)
        c.roundRect(MARGIN_X, PAGE_H - 15 * mm, 9 * mm, 4 * mm, 2 * mm, fill=1, stroke=0)
        c.setFont("Arial-Bold", 7.2)
        c.setFillColor(TEAL_DARK)
        c.drawString(MARGIN_X + 12 * mm, PAGE_H - 13.2 * mm, eyebrow)
        c.setFont("Arial", 7.2)
        c.setFillColor(MUTED)
        c.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 13.2 * mm, "TransCom 0.2.0-beta.1 | 14.07.2026")
        c.setStrokeColor(LINE)
        c.line(MARGIN_X, PAGE_H - 17 * mm, PAGE_W - MARGIN_X, PAGE_H - 17 * mm)
        self.heading(title)

    def finish(self) -> None:
        if self.y < BOTTOM - 1:
            raise RuntimeError(f"Page {self.number} overflowed: y={self.y}")
        c = self.c
        c.setStrokeColor(LINE)
        c.line(MARGIN_X, 12 * mm, PAGE_W - MARGIN_X, 12 * mm)
        c.setFont("Arial", 7.1)
        c.setFillColor(MUTED)
        c.drawString(MARGIN_X, 8.5 * mm, "Lokale Desktop-Beta | Nicht für sicherheitskritische Entscheidungen")
        c.drawRightString(PAGE_W - MARGIN_X, 8.5 * mm, f"{self.number}")
        c.showPage()

    def gap(self, h: float = 3 * mm) -> None:
        self.y -= h

    def heading(self, text: str, sub: str | None = None) -> None:
        p = Paragraph(esc(text), S_H1)
        _, h = p.wrap(CONTENT_W, 40 * mm)
        p.drawOn(self.c, MARGIN_X, self.y - h)
        self.y -= h + 2.2 * mm
        if sub:
            self.para(sub, S_SMALL)
            self.gap(1.2 * mm)

    def h2(self, text: str) -> None:
        self.gap(1.5 * mm)
        p = Paragraph(esc(text), S_H2)
        _, h = p.wrap(CONTENT_W, 20 * mm)
        p.drawOn(self.c, MARGIN_X, self.y - h)
        self.y -= h + 1.4 * mm

    def para(self, text: str, st: ParagraphStyle = S_BODY, width: float = CONTENT_W, x: float | None = None) -> float:
        p = Paragraph(text, st)
        _, h = p.wrap(width, PAGE_H)
        if self.y - h < BOTTOM:
            raise RuntimeError(f"Paragraph overflow on page {self.number}: {shorten(text, 80)}")
        p.drawOn(self.c, MARGIN_X if x is None else x, self.y - h)
        self.y -= h + 1.3 * mm
        return h

    def bullet(self, text: str, color=TEAL) -> None:
        x = MARGIN_X + 5 * mm
        p = Paragraph(text, S_BODY)
        _, h = p.wrap(CONTENT_W - 7 * mm, PAGE_H)
        self.c.setFillColor(color)
        self.c.circle(MARGIN_X + 1.7 * mm, self.y - 4.2, 1.6, fill=1, stroke=0)
        p.drawOn(self.c, x, self.y - h)
        self.y -= h + 1.2 * mm

    def checklist(self, text: str) -> None:
        x = MARGIN_X + 7 * mm
        p = Paragraph(text, S_BODY)
        _, h = p.wrap(CONTENT_W - 8 * mm, PAGE_H)
        self.c.setStrokeColor(TEAL)
        self.c.setLineWidth(0.9)
        self.c.rect(MARGIN_X + 0.3 * mm, self.y - 4.1 * mm, 3.4 * mm, 3.4 * mm, fill=0, stroke=1)
        p.drawOn(self.c, x, self.y - h)
        self.y -= h + 1.5 * mm

    def step(self, number: int, title: str, body: str) -> None:
        circle_x = MARGIN_X + 4.3 * mm
        p = Paragraph(f"<b>{esc(title)}</b><br/>{body}", S_STEP)
        _, h = p.wrap(CONTENT_W - 13 * mm, PAGE_H)
        self.c.setFillColor(TEAL)
        self.c.circle(circle_x, self.y - 4.8 * mm, 4.1 * mm, fill=1, stroke=0)
        self.c.setFillColor(WHITE)
        self.c.setFont("Arial-Bold", 8.5)
        self.c.drawCentredString(circle_x, self.y - 6.1 * mm, str(number))
        p.drawOn(self.c, MARGIN_X + 12 * mm, self.y - h)
        self.y -= max(h, 9 * mm) + 1.8 * mm

    def callout(self, title: str, body: str, kind: str = "info") -> None:
        palette = {
            "info": (BLUE_PALE, BLUE),
            "good": (GREEN_PALE, GREEN),
            "warn": (AMBER_PALE, AMBER),
            "danger": (RED_PALE, RED),
            "teal": (TEAL_PALE, TEAL_DARK),
        }
        bg, accent = palette[kind]
        w = CONTENT_W
        p = Paragraph(f"<b>{esc(title)}</b><br/>{body}", S_NOTE)
        _, h = p.wrap(w - 12 * mm, PAGE_H)
        box_h = h + 7 * mm
        if self.y - box_h < BOTTOM:
            raise RuntimeError(f"Callout overflow on page {self.number}: {title}")
        self.c.setFillColor(bg)
        self.c.roundRect(MARGIN_X, self.y - box_h, w, box_h, 3 * mm, fill=1, stroke=0)
        self.c.setFillColor(accent)
        self.c.roundRect(MARGIN_X, self.y - box_h, 2.2 * mm, box_h, 1 * mm, fill=1, stroke=0)
        p.drawOn(self.c, MARGIN_X + 7 * mm, self.y - box_h + 3.5 * mm)
        self.y -= box_h + 2.4 * mm

    def code(self, text: str) -> None:
        lines = text.splitlines()
        p = Paragraph("<br/>".join(esc(line).replace(" ", "&nbsp;") for line in lines), S_CODE)
        _, h = p.wrap(CONTENT_W - 10 * mm, PAGE_H)
        box_h = h + 7 * mm
        self.c.setFillColor(colors.HexColor("#EFF3F5"))
        self.c.roundRect(MARGIN_X, self.y - box_h, CONTENT_W, box_h, 2 * mm, fill=1, stroke=0)
        p.drawOn(self.c, MARGIN_X + 5 * mm, self.y - box_h + 3.5 * mm)
        self.y -= box_h + 2.2 * mm

    def table(self, rows, widths=None, header=True, font_size=7.7) -> None:
        processed = []
        for r_i, row in enumerate(rows):
            st = S_TABLE_HEAD if header and r_i == 0 else style(
                f"table_{self.number}_{r_i}", fontSize=font_size, leading=font_size + 2.6
            )
            processed.append([Paragraph(cell, st) for cell in row])
        if widths is None:
            widths = [CONTENT_W / len(rows[0])] * len(rows[0])
        t = Table(processed, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ]
        if header:
            commands += [("BACKGROUND", (0, 0), (-1, 0), TEAL_DARK)]
            start = 1
        else:
            start = 0
        for row_index in range(start, len(rows)):
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), WHITE if row_index % 2 else PAPER))
        t.setStyle(TableStyle(commands))
        _, h = t.wrap(CONTENT_W, PAGE_H)
        if self.y - h < BOTTOM:
            raise RuntimeError(f"Table overflow on page {self.number}")
        t.drawOn(self.c, MARGIN_X, self.y - h)
        self.y -= h + 2.5 * mm

    def two_cards(self, left_title: str, left_body: str, right_title: str, right_body: str) -> None:
        gap = 4 * mm
        w = (CONTENT_W - gap) / 2
        entries = [(left_title, left_body), (right_title, right_body)]
        heights = []
        paras = []
        for title, body in entries:
            p = Paragraph(f"<b>{esc(title)}</b><br/>{body}", S_NOTE)
            _, h = p.wrap(w - 10 * mm, PAGE_H)
            paras.append(p)
            heights.append(h)
        box_h = max(heights) + 9 * mm
        for idx, p in enumerate(paras):
            x = MARGIN_X + idx * (w + gap)
            self.c.setFillColor(PAPER)
            self.c.setStrokeColor(LINE)
            self.c.roundRect(x, self.y - box_h, w, box_h, 3 * mm, fill=1, stroke=1)
            p.drawOn(self.c, x + 5 * mm, self.y - box_h + 4.5 * mm)
        self.y -= box_h + 2.5 * mm

    def flow(self, labels: list[str]) -> None:
        n = len(labels)
        gap = 5 * mm
        box_w = (CONTENT_W - gap * (n - 1)) / n
        box_h = 16 * mm
        for i, label in enumerate(labels):
            x = MARGIN_X + i * (box_w + gap)
            self.c.setFillColor(TEAL_PALE if i < n - 1 else GREEN_PALE)
            self.c.setStrokeColor(TEAL if i < n - 1 else GREEN)
            self.c.roundRect(x, self.y - box_h, box_w, box_h, 2.5 * mm, fill=1, stroke=1)
            p = Paragraph(esc(label), style(f"flow_{self.number}_{i}", fontName="Arial-Bold", fontSize=8, leading=10, alignment=TA_CENTER, textColor=TEAL_DARK))
            _, h = p.wrap(box_w - 5 * mm, box_h)
            p.drawOn(self.c, x + 2.5 * mm, self.y - box_h / 2 - h / 2)
            if i < n - 1:
                ax = x + box_w + 1.1 * mm
                ay = self.y - box_h / 2
                self.c.setStrokeColor(MUTED)
                self.c.line(ax, ay, ax + 2.8 * mm, ay)
                self.c.line(ax + 2.8 * mm, ay, ax + 1.4 * mm, ay + 1.2 * mm)
                self.c.line(ax + 2.8 * mm, ay, ax + 1.4 * mm, ay - 1.2 * mm)
        self.y -= box_h + 3 * mm


def cover(c: canvas.Canvas) -> None:
    def ridge(points, fill):
        path = c.beginPath()
        path.moveTo(points[0][0] * mm, points[0][1] * mm)
        for x, y in points[1:]:
            path.lineTo(x * mm, y * mm)
        path.lineTo(points[-1][0] * mm, 0)
        path.lineTo(points[0][0] * mm, 0)
        path.close()
        c.setFillColor(colors.HexColor(fill))
        c.drawPath(path, fill=1, stroke=0)

    c.setFillColor(colors.HexColor("#102F49"))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#153B59"))
    c.circle(PAGE_W + 20 * mm, PAGE_H - 45 * mm, 75 * mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#2B5F86"))
    c.circle(PAGE_W - 5 * mm, PAGE_H - 32 * mm, 32 * mm, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.roundRect(19 * mm, PAGE_H - 33 * mm, 12 * mm, 5 * mm, 2.5 * mm, fill=1, stroke=0)
    c.setStrokeColor(colors.white)
    c.setLineWidth(1.1)
    for x, height in [(22.0, 2.0), (24.0, 4.0), (26.0, 3.0), (28.0, 1.8)]:
        cx = x * mm
        cy = PAGE_H - 30.5 * mm
        c.line(cx, cy - height * mm / 2, cx, cy + height * mm / 2)
    c.setFont("Arial-Bold", 9)
    c.setFillColor(colors.HexColor("#C9D6E0"))
    c.drawString(35 * mm, PAGE_H - 31.5 * mm, "TRANSCOM 0.2.0-BETA.1")
    c.setFont("Georgia-Bold", 31)
    c.setFillColor(WHITE)
    c.drawString(19 * mm, PAGE_H - 68 * mm, "Beta-Handbuch")
    c.setFont("Arial", 16)
    c.setFillColor(colors.HexColor("#D8E2E9"))
    c.drawString(19 * mm, PAGE_H - 80 * mm, "Lokale Live-Transkription für macOS")
    c.setStrokeColor(colors.HexColor("#5B7890"))
    c.line(19 * mm, PAGE_H - 93 * mm, PAGE_W - 19 * mm, PAGE_H - 93 * mm)

    # Verbindliches TransCom-Alpenprofil. Diese vier Polygonzüge sind exakt
    # dieselben Konturen wie im App-Sidebar und auf der Website - kein zweites
    # Bergmotiv und keine zusätzliche Wellenlandschaft.
    ridge([(0, 22.4), (16.8, 30.4), (35.7, 26.4), (60.9, 44.0), (77.7, 34.4), (100.8, 65.6), (113.4, 46.4), (130.2, 35.2), (144.9, 51.2), (161.7, 32.8), (178.5, 44.0), (193.2, 36.8), (210, 49.6)], "#5D7C96")
    ridge([(0, 16.0), (16.8, 25.1), (33.6, 19.2), (52.5, 37.1), (69.3, 22.4), (88.2, 35.8), (109.2, 20.5), (128.1, 32.6), (147.0, 21.8), (168.0, 36.5), (184.8, 26.9), (210, 33.3)], "#466B88")
    ridge([(0, 16.3), (16.8, 22.6), (29.4, 16.8), (42.0, 25.0), (56.7, 15.8), (75.6, 20.2), (94.5, 13.4), (115.5, 19.7), (136.5, 12.5), (159.6, 17.8), (182.7, 11.5), (210, 17.3)], "#345B78")
    ridge([(0, 11.8), (14.7, 17.1), (27.3, 11.5), (42.0, 18.9), (58.8, 10.5), (81.9, 15.5), (102.9, 9.3), (126.0, 14.0), (149.1, 8.4), (172.2, 13.3), (191.1, 9.9), (210, 14.3)], "#1F425D")

    p = Paragraph(
        "Installation, Demo, Livebetrieb, Export, LAN-Viewer, Datenschutz, "
        "Safety Mode, bekannte Grenzen und strukturiertes Beta-Feedback.",
        style("cover_body", fontSize=12.5, leading=18, textColor=WHITE),
    )
    p.wrapOn(c, 145 * mm, 80 * mm)
    p.drawOn(c, 19 * mm, PAGE_H - 128 * mm)

    c.setFillColor(colors.HexColor("#E76522"))
    c.roundRect(19 * mm, 47 * mm, 91 * mm, 13 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Arial-Bold", 9)
    c.drawString(24 * mm, 52 * mm, "BETA | NICHT PRODUKTIONSFREIGEGEBEN")
    c.setFillColor(colors.HexColor("#B9C9D4"))
    c.setFont("Arial", 8.2)
    c.drawString(19 * mm, 31 * mm, "Zielsystem: Apple Silicon (M1 bis M4) | Stand: 14.07.2026")
    c.drawString(19 * mm, 25 * mm, "Geprüft gegen aktuellen Quellcode, Setup und Handoff-Dokumente")
    c.showPage()


def ui_figure(c: canvas.Canvas, variant: str) -> None:
    """A faithful, readable UI reference figure for the handbook."""
    x, y, w, h = 18 * mm, 44 * mm, 174 * mm, 119 * mm
    sidebar_w, bar_h = 43 * mm, 10 * mm
    c.setFillColor(colors.HexColor("#FFF EFA".replace(" ", "")))
    c.roundRect(x, y, w, h, 3 * mm, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#CFC9BF"))
    c.roundRect(x, y, w, h, 3 * mm, fill=0, stroke=1)
    c.setFillColor(colors.HexColor("#F6F2EB"))
    c.roundRect(x, y + h - bar_h, w, bar_h, 3 * mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#E7795F"))
    c.circle(x + 6 * mm, y + h - 5 * mm, 1.25 * mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#E7BD66"))
    c.circle(x + 10 * mm, y + h - 5 * mm, 1.25 * mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#77AC7F"))
    c.circle(x + 14 * mm, y + h - 5 * mm, 1.25 * mm, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont("Georgia-Bold", 7.2)
    c.drawCentredString(x + w / 2, y + h - 6.2 * mm, "TransCom")

    c.setFillColor(colors.HexColor("#153B59"))
    c.rect(x, y, sidebar_w, h - bar_h, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#D8E2E9"))
    c.setFont("Arial-Bold", 5.4)
    c.drawString(x + 5 * mm, y + h - 16 * mm, "SESSION")
    c.setFont("Georgia-Bold", 8.2)
    c.setFillColor(WHITE)
    c.drawString(x + 5 * mm, y + h - 22 * mm, "Generalprobe")
    nav = [("Dashboard", False), ("Audio-Datei", variant == "audio"), ("Live-Feed", variant == "live"), ("Ergebnisse", variant == "export"), ("Einstellungen", False)]
    nav_y = y + h - 34 * mm
    for label, active in nav:
        if active:
            c.setFillColor(colors.HexColor("#214D6F"))
            c.rect(x, nav_y - 4.2 * mm, sidebar_w, 8 * mm, fill=1, stroke=0)
            c.setFillColor(TEAL)
            c.rect(x, nav_y - 4.2 * mm, 1.3 * mm, 8 * mm, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#FFFFFF" if active else "#B9C9D4"))
        c.setFont("Arial-Bold" if active else "Arial", 6.5)
        c.drawString(x + 6 * mm, nav_y, label)
        nav_y -= 10 * mm

    px, py, pw = x + sidebar_w + 7 * mm, y + 8 * mm, w - sidebar_w - 14 * mm
    c.setFillColor(colors.HexColor("#1C2F43"))
    c.setFont("Georgia-Bold", 12)
    title = {"audio": "Audio-Datei-Demo", "live": "Live-Transkript", "export": "Ergebnisse & Export"}[variant]
    c.drawString(px, y + h - 20 * mm, title)
    c.setFillColor(MUTED)
    c.setFont("Arial", 6.2)
    c.drawString(px, y + h - 25 * mm, "Generalprobe · Deutsch + Englisch · lokal verarbeitet")
    c.setStrokeColor(LINE)
    c.line(px, y + h - 28 * mm, x + w - 6 * mm, y + h - 28 * mm)

    if variant == "audio":
        c.setFillColor(colors.HexColor("#F1EDE5"))
        c.roundRect(px, y + h - 58 * mm, pw, 22 * mm, 2 * mm, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont("Arial-Bold", 7.4)
        c.drawString(px + 5 * mm, y + h - 44 * mm, "Demo-Feed.wav")
        c.setFillColor(MUTED)
        c.setFont("Arial", 6.1)
        c.drawString(px + 5 * mm, y + h - 49 * mm, "Mitgelieferte Probe · 00:00:00")
        c.setFillColor(TEAL)
        c.roundRect(px + pw - 39 * mm, y + h - 53 * mm, 32 * mm, 9 * mm, 2 * mm, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Arial-Bold", 6.4)
        c.drawCentredString(px + pw - 23 * mm, y + h - 49.7 * mm, "Demo starten")
        bars = [7, 15, 10, 23, 31, 16, 12, 27, 19, 9, 18, 28, 13]
        bx = px + 7 * mm
        for level in bars:
            c.setFillColor(colors.HexColor("#437596"))
            c.rect(bx, py + 8 * mm, 1.8 * mm, level * .68 * mm, fill=1, stroke=0)
            bx += 4.1 * mm
        c.setFillColor(MUTED)
        c.setFont("Arial", 6.2)
        c.drawString(px, py + 4 * mm, "1. Datei wählen   2. Feed starten   3. Transkript beobachten")
    else:
        lines = [("00:12", "REGIE", "Wir gehen in dreißig Sekunden live."), ("00:16", "STAGE", "Copy. Kamera zwei ist bereit."), ("00:21", "AUDIO", "The host microphone is open."), ("00:27", "REGIE", "Danke. Stand by … und los.")]
        row_y = y + h - 37 * mm
        for timestamp, speaker, text in lines:
            c.setStrokeColor(colors.HexColor("#E5E0D8"))
            c.line(px, row_y - 5 * mm, x + w - 6 * mm, row_y - 5 * mm)
            c.setFillColor(colors.HexColor("#8A99A5"))
            c.setFont("Courier", 5.5)
            c.drawString(px, row_y, timestamp)
            c.setFillColor(TEAL if speaker == "STAGE" else BLUE)
            c.setFont("Arial-Bold", 5.5)
            c.drawString(px + 18 * mm, row_y, speaker)
            c.setFillColor(INK)
            c.setFont("Arial", 6.5)
            c.drawString(px + 37 * mm, row_y, text)
            row_y -= 11 * mm
        if variant == "export":
            c.setFillColor(TEAL)
            c.roundRect(px + pw - 36 * mm, py + 6 * mm, 30 * mm, 9 * mm, 2 * mm, fill=1, stroke=0)
            c.setFillColor(WHITE)
            c.setFont("Arial-Bold", 6.1)
            c.drawCentredString(px + pw - 21 * mm, py + 9.3 * mm, "TXT / CSV exportieren")
        else:
            c.setFillColor(colors.HexColor("#EAF6EF"))
            c.roundRect(px, py + 5 * mm, 47 * mm, 9 * mm, 2 * mm, fill=1, stroke=0)
            c.setFillColor(GREEN)
            c.setFont("Arial-Bold", 6.1)
            c.drawString(px + 4 * mm, py + 8.2 * mm, "●  Aufzeichnung läuft")


def build() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=A4, pageCompression=1)
    c.setTitle("TransCom Beta-Handbuch")
    c.setAuthor("TransCom")
    c.setSubject("Deutsches Benutzerhandbuch für die TransCom macOS Beta")
    cover(c)

    p = Page(c, 2, "Starter oder Full?")
    p.callout("Zwei eindeutig getrennte Builds", "Die Edition ist Bestandteil des ausgelieferten App-Builds und wird in der Oberfläche angezeigt. Fehlende oder ungültige Editionen fallen sicher auf Starter zurück.", "teal")
    p.table([
        ["Edition", "Neue Transkription", "Gespeicherte Transkripte", "Export"],
        ["Starter", "Je Session exakt maximal 60 Sekunden", "Ansehen, durchsuchen, Sprecher korrigieren und verwalten", "Gesperrt"],
        ["Full - einmalig 199 €", "Keine 60-Sekunden-Grenze", "Ansehen, durchsuchen, Sprecher korrigieren und verwalten", "TXT und CSV"],
    ], widths=[35*mm, 45*mm, 65*mm, CONTENT_W-145*mm])
    p.callout("Was nach 60 Sekunden passiert", "Starter stoppt serverseitig automatisch sowohl den Audiofeed als auch die laufende Session. Das bisherige Transkript bleibt gespeichert. Dieselbe Session kann nicht einfach weiterlaufen; du kannst eine <b>neue Session</b> anlegen und erhältst dort erneut maximal 60 Sekunden.", "warn")
    p.h2("Auslieferung in dieser Beta")
    p.bullet("Starter und Full werden als getrennte, eindeutig benannte App-ZIPs gebaut.")
    p.bullet("Es gibt derzeit keinen Checkout, keine Lizenzaktivierung und keinen In-App-Kauf.")
    p.bullet("TransCom Full wird nach persönlicher Abstimmung ausgeliefert. Der angegebene Preis beträgt einmalig 199 €.")
    p.h2("Start in vier Schritten")
    p.flow(["Edition prüfen", "Demo starten", "Ergebnis prüfen", "Neue Session / Export"])
    p.step(1, "App öffnen", "Beim ersten Start bis zu 60 Sekunden für Backend und Modellinitialisierung einplanen.")
    p.step(2, "Edition lesen", "Unter der Audioquelle steht <b>TransCom Starter</b> oder <b>TransCom Full</b> mit den jeweiligen Grenzen.")
    p.step(3, "Demo testen", "<b>Demo</b> wählen und <b>Transkription starten</b>. Starter endet automatisch nach exakt 60 Sekunden.")
    p.step(4, "Weiterarbeiten", "In Starter eine neue Session für den nächsten 60-Sekunden-Test anlegen; in Full bei Bedarf TXT oder CSV exportieren.")
    p.callout("Sicherheitsgrenze", "TransCom darf in dieser Beta keine sicherheitskritische Kommunikation, Freigabe oder Maschinensteuerung ersetzen. Jede relevante Aussage muss über den Original-Audiokanal bestätigt werden.", "danger")
    p.finish()

    p = Page(c, 3, "Installation auf Apple Silicon")
    p.h2("Geliefertes Beta-Paket")
    p.step(1, "Richtiges ZIP entpacken", "<b>TransCom-Starter-0.2.0-beta.1-arm64-mac.zip</b> oder <b>TransCom-Full-0.2.0-beta.1-arm64-mac.zip</b> im Finder doppelklicken.")
    p.step(2, "App ablegen", "<b>TransCom.app</b> nach <b>Programme</b> oder in einen lokalen Testordner kopieren. Nicht direkt aus dem ZIP starten.")
    p.step(3, "Erstmals öffnen", "Rechtsklick auf <b>TransCom.app</b> und <b>Öffnen</b> wählen. Die Warnung des nicht signierten Beta-Builds bewusst bestätigen.")
    p.step(4, "Berechtigungen", "Wenn macOS fragt, Mikrofonzugriff erlauben. Für den LAN-Viewer kann zusätzlich der Zugriff auf das lokale Netzwerk nötig sein.")
    p.callout("Betreute Auslieferung", "Der aktuelle Release-Aufbau bündelt die Backend-Laufzeit, ONNX-Modelle und alle drei gepinnten ASR-Snapshots für den Offline-Betrieb. Das große ZIP immer vollständig übertragen und die mitgeteilte SHA-256-Prüfsumme abgleichen. Der Beta-Build ist weiterhin nicht regulär notarisiert.", "warn")
    p.h2("Wenn macOS weiterhin blockiert")
    p.para("Öffne <b>Systemeinstellungen - Datenschutz &amp; Sicherheit</b> und bestätige den blockierten Start, sofern du das Paket vom vorgesehenen Testkanal erhalten und die Prüfsumme abgeglichen hast.")
    p.code('xattr -dr com.apple.quarantine "/Applications/TransCom.app"')
    p.para("Den Terminal-Befehl nur für genau diese geprüfte App verwenden. Er entfernt die Quarantäne-Markierung; er signiert oder verifiziert die App nicht.", S_SMALL)
    p.h2("Login")
    p.para("Der lokale Desktop-Build startet standardmäßig im Auth-Bypass und verlangt kein Login. Erscheint eine Login-Maske, verwendest du die authentifizierte Web-Beta und brauchst die separat bereitgestellten Zugangsdaten.")
    p.para("Starter und Full benötigen keine Aktivierung. Die Edition wird durch das jeweils ausgelieferte, getrennt benannte App-Paket festgelegt.", S_SMALL)
    p.finish()

    p = Page(c, 4, "Erster Start und Oberfläche")
    p.callout("Bereit ist die App erst dann", "Der Verbindungsdialog ist verschwunden, unten steht <b>Bereit</b>, und links sind Live, Demo und Datei auswählbar. Bei fehlender Audio-Engine siehe Seite 15.", "good")
    p.h2("Die drei Arbeitsbereiche")
    p.table([
        ["Bereich", "Was du dort tust", "Wichtige Elemente"],
        ["Links", "Session und Audioquelle vorbereiten", "Transkriptname, Speicherort, Live/Demo/Datei, Audioeingang, Start/Stop"],
        ["Mitte", "Laufendes Ergebnis beobachten", "Zeit, Sprecher/Channel, Text, Korrekturauswahl, Suche"],
        ["Rechts", "Gespeicherte Sessions verwalten", "Neu, Öffnen, Finder, Auswählen, Löschen"],
        ["Optionen", "Zusatzfunktionen öffnen", "Stimmen erkennen, Live-Ansicht teilen, ggf. Beta-Zugänge"],
        ["Statusleiste", "Technischen Zustand prüfen", "Backend/Modell, Gerät, Engine-Meldung, Laufzeit"],
    ], widths=[27*mm, 60*mm, CONTENT_W-87*mm])
    p.h2("Erstkonfiguration")
    p.step(1, "Transkript benennen", "Einen eindeutigen Namen eintragen, etwa <b>Probe 14. Juli - Bühne</b>.")
    p.step(2, "Speicherort prüfen", "Ohne Auswahl speichert der Desktop-Build dauerhaft unter <b>Library/Application Support/TransCom/data/sessions</b>. Unter <b>Speicherort</b> kann optional ein anderer beschreibbarer Ordnerpfad eingetragen werden.")
    p.step(3, "Quelle wählen", "<b>Demo</b> für den ersten Test, <b>Datei</b> für eigene Aufnahmen, <b>Live</b> für ein Eingabegerät.")
    p.step(4, "Starten", "Der große Button legt bei Bedarf die Session an, startet sie und startet den Audiofeed in einem Ablauf.")
    p.callout("Edition sichtbar prüfen", "Unter dem Start-/Stop-Bereich steht <b>TransCom Starter</b> oder <b>TransCom Full</b>. Wenn die Anzeige nicht zum Dateinamen des ausgelieferten ZIPs passt, den Test stoppen und den Support informieren.", "warn")
    p.finish()

    p = Page(c, 5, "Audio-Datei-Demo")
    p.h2("Der zuverlässigste Einstieg")
    p.para("Die Demo nutzt eine mitgelieferte Testaufnahme und denselben Capture-, VAD- und Transkriptionspfad wie eine eigene Datei. So lassen sich Installation und grundlegender Ablauf ohne Audio-Routing prüfen.")
    p.step(1, "Session vorbereiten", "Einen eindeutigen Namen eintragen und die angezeigte Edition prüfen.")
    p.step(2, "Demo auswählen", "Im Dreifachschalter <b>Demo - Testaufnahme</b> wählen. Die Dateizusammenfassung muss <b>TransCom-Testaufnahme</b> zeigen.")
    p.step(3, "Transkription starten", "Den großen Button drücken. Wiedergabe und Verarbeitung starten gemeinsam.")
    p.step(4, "Geduld beim ersten Text", "Je nach Modellinitialisierung und Segmentgrenze können mehrere Sekunden vergehen. Der letzte Referenzwert für die erste Ausgabe lag bei ca. 3,59 Sekunden, reale Systeme können langsamer sein.")
    p.step(5, "Limit oder Stop", "Starter stoppt Feed und Session nach exakt 60 Sekunden automatisch. Full läuft bis <b>Transkription beenden</b>; nur dort ist anschließend TXT/CSV-Export verfügbar.")
    p.h2("Eigene Aufnahme")
    p.para("Unter <b>Datei - Eigene Aufnahme</b> öffnet die Desktop-App einen Dateidialog. Unterstützte Filter: WAV/WAVE, AIFF/AIF, MP3 und M4A. Dateien laufen in Echtzeit. Starter verarbeitet pro neuer Session maximal die ersten 60 Sekunden; Full läuft ohne diese Zeitgrenze.")
    p.two_cards("Was du hören solltest", "Im Datei-/Demo-Modus wird Audio über die lokale Wiedergabe überwacht. Prüfe macOS-Ausgabe, Lautstärke und Stummschaltung.", "Was du sehen solltest", "Status <b>Transkription läuft</b>, zunehmende Laufzeit und nach Segmentabschluss neue Zeilen in der Mitte.")
    p.callout("Kein Ton ist nicht gleich kein Feed", "Wenn das Monitoring stumm ist, kann die Backend-Verarbeitung dennoch laufen. Beurteile deshalb getrennt: hörbare Wiedergabe, aktiver Feed und erscheinende Transkriptzeilen.", "info")
    p.finish()

    p = Page(c, 6, "Session und Feed verstehen")
    p.callout("Ein Button, drei Zustände", "Die aktuelle UI bündelt Session-Erstellung, Session-Start und Feed-Start im großen Start-Button. Intern bleiben diese Zustände getrennt. Das erklärt manche verwirrende Übergänge in der Beta.", "teal")
    p.h2("Lebenszyklus")
    p.flow(["Name + Ordner", "Session anlegen", "Session live", "Feed aktiv", "Stop + speichern"])
    p.table([
        ["Anzeige", "Bedeutung", "Operator-Aktion"],
        ["bereit", "Session/Feed läuft nicht", "Quelle kontrollieren und starten"],
        ["läuft", "Sessionstatus ist live", "Nicht Namen oder Speicherort wechseln"],
        ["Transkription läuft", "Mindestens ein Audiokanal ist aktiv", "Pegel/Audio und neue Zeilen beobachten"],
        ["Starter-Limit erreicht", "60 Sekunden dieser Session sind verbraucht; Feed und Session wurden serverseitig gestoppt", "Neue Session anlegen, nicht dieselbe neu starten"],
        ["Audio-Engine wird verbunden", "WebSocket/Backend noch nicht bereit", "Warten; nach 8 Sekunden Fehlermeldung prüfen"],
        ["Audio-Engine nicht erreichbar", "Backend oder Portverbindung fehlgeschlagen", "App neu starten, Modelle/Ports prüfen"],
    ], widths=[38*mm, 62*mm, CONTENT_W-100*mm])
    p.h2("Gespeicherte Sessions")
    p.para("Rechts unter <b>Gespeicherte Transkripte</b> kannst du in beiden Editionen Sessions ansehen, durchsuchen, Sprecherzuordnungen korrigieren, im Finder zeigen, auswählen oder in den Papierkorb bewegen. Freie Textbearbeitung ist weiterhin nicht vorgesehen.")
    p.callout("Löschen ist eine echte Dateisystemaktion", "Die App verschiebt bestätigte TransCom-Sessionordner in den macOS-Papierkorb. Full kann vorher TXT/CSV exportieren; Starter bewahrt das Ergebnis nur als lokale Session auf.", "warn")
    p.h2("Session-Inhalt")
    p.code("<session-ordner>/\n  session.json\n  transcript.db\n  exports/\n  profiles/")
    p.para("Die Datenbank ist die Arbeitskopie. TXT/CSV-Exporte sind transportable Ausgaben, aber kein vollständiges Backup aller Session-Metadaten.", S_SMALL)
    p.finish()

    p = Page(c, 7, "Livebetrieb und Audio-Routing")
    p.h2("Direkter Hardware-Eingang")
    p.step(1, "Signal verbinden", "Intercom-Mix, Mischpult oder Mikrofon über ein USB-Audiointerface mit dem Mac verbinden.")
    p.step(2, "Live wählen", "Unter <b>Live - Eingang hören</b> das gewünschte Gerät im Feld <b>Audioeingang</b> auswählen.")
    p.step(3, "Liste aktualisieren", "Wurde das Gerät erst nach App-Start verbunden, <b>Eingänge neu laden</b> drücken.")
    p.step(4, "Transkription starten", "Mit einem kurzen Sprachtest beginnen und erst dann den echten Feed aufschalten.")
    p.h2("Player, REAPER oder DAW über Loopback")
    p.para("macOS stellt den Ausgang einer App nicht automatisch als Eingang bereit. Richte ein virtuelles Gerät wie BlackHole oder Loopback ein, route die Player-/DAW-Ausgabe dorthin und wähle dasselbe Gerät in TransCom als Audioeingang.")
    p.flow(["Player/DAW", "BlackHole/Loopback", "TransCom Live", "Lokale ASR"])
    p.h2("Pegel- und Sprachpraxis")
    p.bullet("Einen sauberen Summenfeed ohne Clipping liefern; sehr leise Sprache kann vom VAD verworfen werden.")
    p.bullet("Gleichzeitige Sprecher möglichst vermeiden. Ein gemischter Feed kann Überlappungen nicht zuverlässig trennen.")
    p.bullet("Kurze, klare Äußerungen verbessern Segmentierung; extrem fragmentierte Calls bleiben anspruchsvoll.")
    p.bullet("Deutsch und Englisch sind die vorgesehenen Sprachen; Fachbegriffe, Namen und Codes müssen im Feedback markiert werden.")
    p.callout("Vor der Produktion testen", "Mindestens fünf Minuten mit derselben Hardware, demselben Routing und typischen Sprechern testen. Diese Beta hat keine Produktionsfreigabe.", "danger")
    p.finish()

    p = Page(c, 8, "Live-Transkript bedienen")
    p.h2("Eine Zeile lesen")
    p.table([
        ["Element", "Bedeutung"],
        ["Zeit", "Lokaler Segment-Zeitpunkt"],
        ["Sprecher/Channel", "Automatische Zuordnung oder MIX/Unknown; Farbe dient nur der Orientierung"],
        ["Text", "Lokale ASR-Ausgabe; in der Beta nicht direkt editierbar"],
        ["Sprecher-Dropdown", "Manuelle Korrektur der Sprecherzuordnung"],
        ["PRÜFEN / BESTÄTIGT", "Nur im aktivierten Safety Mode: Bestätigungspflicht für vorgeschlagene Katalogbefehle"],
        ["Roh erkannt / Zweitprüfung", "Auditinformationen, wenn Safety-Verarbeitung beteiligt war"],
    ], widths=[48*mm, CONTENT_W-48*mm])
    p.h2("Sprecher korrigieren")
    p.step(1, "Dropdown öffnen", "Rechts in der betroffenen Zeile den gewünschten Namen auswählen.")
    p.step(2, "Korrektur prüfen", "Die App speichert korrigierte Sprecher-ID und Namen, ohne die ursprüngliche automatische Zuordnung zu vernichten.")
    p.para("Der Transkripttext selbst ist absichtlich nicht editierbar. Einen Fehler daher mit Zeitstempel als <b>erwartet / erkannt</b> im Feedback festhalten.")
    p.h2("Suche und laufende Aktualisierung")
    p.bullet("Das Suchfeld <b>Transkript durchsuchen</b> markiert Treffer im aktuell geladenen Transkript.")
    p.bullet("Wenn du nach oben scrollst, kann ein Banner auf neue Einträge hinweisen.")
    p.bullet("Backend-Aktualisierungen mit derselben Segment-ID ersetzen eine bestehende Zeile. Die frühere erste Doppelzeile ist gezielt adressiert, aber im realen UI noch zu bestätigen.")
    p.callout("Nie nur dem Text vertrauen", "Bei Namen, Zahlen, Richtungen, Freigaben, Stopps und Notfällen immer den Original-Audiokanal als maßgeblich behandeln.", "danger")
    p.finish()

    p = Page(c, 9, "Stimmen erkennen")
    p.para("Der Stimmen-Workflow ist optional. Transkription funktioniert ohne Check-in; dann erscheinen Channel-/Fallback-Labels. Die automatische Sprecherzuordnung ist Beta und muss manuell kontrolliert werden.")
    p.h2("Check-in")
    p.step(1, "Optionen öffnen", "Links auf <b>Optionen</b> klicken und <b>Stimmen erkennen</b> aufklappen.")
    p.step(2, "Person anlegen", "Namen eingeben und <b>Hinzufügen</b> wählen. Bis zu acht Sprecher sind vorgesehen.")
    p.step(3, "Eingang prüfen", "Die Stimmprobe nimmt den ausgewählten Live-Eingang auf. Die Person sollte allein und deutlich sprechen.")
    p.step(4, "Stimmprobe starten", "Standard sind 10 Sekunden; einstellbar sind 3 bis 20 Sekunden. Während der Fortschrittsanzeige kontinuierlich sprechen.")
    p.step(5, "Qualität prüfen", "Die UI zeigt Qualitätsbalken und <b>Stimme erkannt</b> oder <b>kurze Stimmprobe nötig</b>.")
    p.h2("Gute Stimmprobe")
    p.two_cards("Hilfreich", "Normale Sprechlautstärke, ruhige Umgebung, typisches Mikrofon, vollständige 8 bis 12 Sekunden, nur eine Person.", "Problematisch", "Überlappungen, Musik, Raumhall, wechselnde Mikrofone, Clipping oder extrem kurze Aufnahme.")
    p.h2("Aktueller Reifegrad")
    p.bullet("Das ONNX-Speaker-Modell ist lokal eingebunden; Zuordnung und Schwellenwert müssen unter realen Bedingungen weiter validiert werden.")
    p.bullet("Unknown und Fehlzuordnungen sind zu erwarten. Nutze das Zeilen-Dropdown zur Korrektur.")
    p.bullet("Ein Check-in ist keine Identitätsprüfung und darf nicht als Zugangskontrolle verwendet werden.")
    p.finish()

    p = Page(c, 10, "Editionen, Export und Archivierung")
    p.table([
        ["Funktion", "Starter", "Full"],
        ["Gespeicherte Sessions", "Ansehen, durchsuchen, Sprecher korrigieren, verwalten", "Ansehen, durchsuchen, Sprecher korrigieren, verwalten"],
        ["Neue Transkription", "Exakt max. 60 s je neuer Session", "Ohne 60-s-Grenze"],
        ["Export", "In UI und Backend gesperrt", "TXT und CSV"],
        ["Preis / Bezug", "Beta-Build", "Einmalig 199 €, persönliche Auslieferung"],
    ], widths=[43*mm, 60*mm, CONTENT_W-103*mm])
    p.h2("Exportieren - nur Full")
    p.step(1, "Session öffnen", "Das gewünschte aktuelle oder gespeicherte Transkript laden.")
    p.step(2, "Format wählen", "Links <b>Exportieren</b> öffnen und <b>Als TXT</b> oder <b>Als CSV</b> wählen.")
    p.step(3, "Ziel wählen", "Im Desktop-Build einen Dateinamen und einen Speicherort außerhalb der App bestätigen.")
    p.table([
        ["Format", "Geeignet für", "Enthält"],
        ["TXT", "Schnelles Lesen und Teilen", "Zeit, Channel-Kürzel, Text; Safety-Markierungen und Rohtext falls vorhanden"],
        ["CSV", "Auswertung und Vergleich", "Zeit, Channel, Text, Confidence sowie ausführliche Safety-/Auditfelder"],
    ], widths=[25*mm, 52*mm, CONTENT_W-77*mm])
    p.callout("Starter-Export ist bewusst gesperrt", "Der Button zeigt <b>Exportieren · Full</b> und ist deaktiviert. Auch direkte Exportanfragen weist das Backend zurück. Für Export wird der getrennte Full-Build benötigt; es gibt keinen In-App-Kauf oder Aktivierungsdialog.", "info")
    p.callout("Was der Export nicht ist", "TXT und CSV sind keine vollständige Session-Sicherung. Bewahre für eine reproduzierbare Untersuchung zusätzlich <b>session.json</b> und <b>transcript.db</b> auf.", "warn")
    p.h2("Empfohlene Ablagestruktur")
    p.code("TransCom Tests/\n  2026-07-14_Demo/\n    export.txt\n    export.csv\n    session.json\n    transcript.db\n    feedback.txt")
    p.h2("Datenschutz beim Weitergeben")
    p.bullet("Exporte können Namen, Produktionsinhalte und sicherheitsbezogene Kommunikation enthalten.")
    p.bullet("Vor Versand Empfänger und Übertragungsweg prüfen; TransCom verschlüsselt Exportdateien nicht.")
    p.bullet("Für Fehlermeldungen möglichst kurze, freigegebene Audiobeispiele statt vollständiger vertraulicher Mitschnitte verwenden.")
    p.finish()

    p = Page(c, 11, "LAN-Viewer")
    p.para("Der LAN-Viewer zeigt die letzten Transkriptsegmente schreibgeschützt auf einem zweiten Gerät im selben lokalen Netzwerk. Er ist für Beobachter gedacht, nicht für Korrektur oder Export.")
    p.h2("Starten")
    p.step(1, "Optionen öffnen", "<b>Live-Ansicht teilen</b> aufklappen.")
    p.step(2, "Link erzeugen", "<b>Link erzeugen</b> klicken. TransCom startet standardmäßig einen lokalen Server auf Port 8787 und erzeugt einen zufälligen Token.")
    p.step(3, "Kopieren", "Den vollständigen Link inklusive <b>?token=...</b> kopieren und nur an vorgesehene Zuschauer senden.")
    p.step(4, "Beenden", "Nach dem Test <b>Freigabe stoppen</b>. Der bisherige Link wird ungültig.")
    p.h2("Voraussetzungen")
    p.bullet("Mac und Zuschauergerät befinden sich im selben vertrauenswürdigen LAN/WLAN.")
    p.bullet("Firewall, VPN oder Client-Isolation blockieren Port 8787 nicht.")
    p.bullet("Die im Link angezeigte IP-Adresse ist vom Zuschauergerät erreichbar.")
    p.h2("Schutzwirkung und Grenze")
    p.table([
        ["Vorhanden", "Nicht vorhanden"],
        ["Zufälliger URL-Token", "TLS/HTTPS-Verschlüsselung"],
        ["Read-only Oberfläche", "Benutzerbezogene Rechte"],
        ["403 ohne gültigen Token", "Schutz, wenn der Link weitergeleitet oder protokolliert wird"],
        ["Stop invalidiert Freigabe", "Internet-Hosting oder sichere Fernfreigabe"],
    ], widths=[CONTENT_W/2, CONTENT_W/2])
    p.callout("Nur vertrauenswürdiges Netz", "Der Link läuft über unverschlüsseltes HTTP. Keine vertraulichen Transkripte in öffentlichen, fremden oder gemeinsam genutzten Netzwerken teilen.", "danger")
    p.finish()

    p = Page(c, 12, "Datenschutz und Offline-Prinzip")
    p.h2("Was lokal bleibt")
    p.bullet("Audioaufnahme, VAD, Speaker-Verarbeitung und Transkription laufen lokal auf dem Mac.")
    p.bullet("Sessions werden dauerhaft im lokalen Benutzerbereich oder im optional gewählten Ordner gespeichert; Full-Exporte am gewählten Zielpfad.")
    p.bullet("Der betreute Release-Build bündelt die drei fest gepinnten ASR-Snapshots; die Runtime löst sie offline aus dem mitgelieferten Modellcache.")
    p.h2("Offline heißt nicht netzwerkisoliert")
    p.para("TransCom benötigt im normalen Betrieb keine Cloud-ASR. Gleichzeitig startet die Desktop-Beta lokale Web-/WebSocket-Dienste und optional den LAN-Viewer. Der Desktop-Build verwendet standardmäßig Auth-Bypass. Nutze ihn deshalb nur auf einem vertrauenswürdigen Testnetz und bei aktivierter macOS-Firewall.")
    p.callout("Sensible Daten", "Keine vertraulichen Produktionsmitschnitte verwenden, wenn der lokale Rechner, der gewählte Session-Ordner oder der LAN-Link nicht entsprechend geschützt sind. TransCom bietet derzeit keine Verschlüsselung ruhender Sessiondaten.", "warn")
    p.h2("Datenorte")
    p.table([
        ["Daten", "Ort / Verhalten"],
        ["Session", "Standard: <b>Library/Application Support/TransCom/data/sessions</b>; optional gewählter Ordner"],
        ["Export", "Nur Full; vom Operator im Speicherdialog gewählter Pfad"],
        ["ASR-Modelle", "Mitgelieferter Offline-Modellcache im App-Paket"],
        ["Speaker/VAD-Modelle", "Im App-/Projektpaket unter <b>models/</b>"],
        ["LAN-Viewer", "Temporärer HTTP-Dienst; Token lebt nur während aktiver Freigabe"],
    ], widths=[39*mm, CONTENT_W-39*mm])
    p.h2("Löschen")
    p.para("App schließen, Sessionordner und Full-Exporte gezielt entfernen und den Papierkorb leeren. Das Löschen der App entfernt die dauerhaften Sessiondaten im Benutzerbereich nicht automatisch.")
    p.finish()

    p = Page(c, 13, "Safety Mode")
    p.callout("Nicht mit Maschinensteuerung verwechseln", "Safety Mode erkennt nur ausgewählte kurze Katalogphrasen und verlangt eine Bestätigung im Transkript. Er führt niemals eine Maschinenaktion aus.", "danger")
    p.h2("Aktivierung")
    p.para("Safety Mode ist standardmäßig aus und besitzt in der aktuellen UI keinen Schalter. Er wird nur für betreute technische Tests vor dem Start des Backends aktiviert:")
    p.code("TRANSCOM_SAFETY_COMMAND_MODE=1 backend/.venv/bin/python backend/main.py")
    p.h2("Verarbeitungsprinzip")
    p.flow(["Kurze Äußerung", "Katalogvergleich", "ggf. Zweitprüfung", "PRÜFEN", "Operator bestätigt"])
    p.bullet("Nur Äußerungen bis drei Sekunden kommen für einen Katalogvorschlag infrage.")
    p.bullet("Exakte erlaubte Phrasen können direkt markiert werden; geeignete Near-Matches können durch das gepinnte faster-whisper-Small-Modell unabhängig zweitgeprüft werden.")
    p.bullet("Negationen, zusätzliche Wörter, Gegenteile und mehrdeutige/zu schwache Treffer bleiben ungelöst und werden nicht in Befehle umgeschrieben.")
    p.bullet("Rohtext, Matchdaten, Katalog-ID, bestätigende Person, Zeit und Bestätigungsereignis bleiben für Audit und Export erhalten.")
    p.h2("Operator-Regel")
    p.step(1, "Audio hören", "Nicht nur die vorgeschlagene Textzeile lesen.")
    p.step(2, "Bedeutung prüfen", "Negation, Richtung, Zahl, Ziel und Kontext vollständig bestätigen.")
    p.step(3, "Nur dokumentieren", "<b>Bestätigen</b> markiert das Transkript; eine reale Aktion muss weiterhin über den freigegebenen Betriebsprozess erfolgen.")
    p.finish()

    p = Page(c, 14, "Bekannte Beta-Grenzen")
    p.callout("Release-Gate", "Der aktuelle Engpass ist nicht die Zahl der Funktionen, sondern Vertrauen in Erkennungsqualität, Latenz und den echten Operator-Ablauf.", "warn")
    p.table([
        ["Risiko", "Aktueller Stand", "Umgang im Test"],
        ["Reale ASR-Qualität", "Vom Nutzer weiterhin als deutlich unter Ziel bewertet; Benchmark-WER 0,2667 ist kein Produktionsnachweis", "Audio + erwartet/erkannt mit Zeitstempel sichern"],
        ["Erste Ausgabe", "Referenz ca. 3,59 s; subjektiv noch zu langsam", "Startlatenz und spätere Zeilenlatenz getrennt bewerten"],
        ["Erste Doppelzeile", "Gezielter UI-Fix vorhanden, Real-UI-Bestätigung offen", "Jedes Auftreten dokumentieren"],
        ["Session/Feed-UX", "Interne Zustände sind gebündelt und leicht missverständlich", "Statusleiste und großen Start/Stop-Button beachten"],
        ["Speaker-Zuordnung", "Lokal implementiert, real noch unzureichend validiert", "Manuell korrigieren; nie als Identität nutzen"],
        ["Starter-Grenze", "Feed und Session stoppen nach exakt 60 s serverseitig", "Für weitere Aufnahme eine neue Session anlegen"],
        ["Editionsauslieferung", "Getrennte Starter-/Full-Builds; keine Aktivierung", "Dateiname und Anzeige vor Test abgleichen"],
        ["Auth-Bypass", "Desktop-Beta startet ohne Login", "Nur vertrauenswürdiges Testnetz; keine fremde Umgebung"],
        ["Signierung", "Beta-Build ist nicht signiert/notarisiert", "Herkunft und Prüfsumme kontrollieren"],
    ], widths=[34*mm, 72*mm, CONTENT_W-106*mm], font_size=6.9)
    p.h2("Nicht als Fehler missverstehen")
    p.bullet("Datei-Feeds laufen in Echtzeit und sind nicht für beschleunigte Stapeltranskription gedacht.")
    p.bullet("Transkripttext ist nicht editierbar; nur Sprecherzuordnung kann korrigiert werden.")
    p.bullet("LAN-Viewer ist read-only und auf das lokale Netzwerk begrenzt.")
    p.finish()

    p = Page(c, 15, "Troubleshooting: Start und Modelle")
    p.table([
        ["Symptom", "Prüfung", "Maßnahme"],
        ["App öffnet nicht", "Gatekeeper-Warnung? App direkt aus ZIP?", "ZIP entpacken; App lokal ablegen; Rechtsklick - Öffnen; Datenschutz &amp; Sicherheit prüfen"],
        ["Audio-Engine bleibt verbunden", "Nach 60 s weiterhin Overlay?", "App komplett beenden und neu starten; genug freien Speicher prüfen"],
        ["Audio-Engine nicht erreichbar", "Backend-Modellfehler oder Ports belegt", "Freigegebenes Modelpaket/Setup prüfen; andere TransCom-/Python-Prozesse beenden"],
        ["Modell nicht gefunden", "ZIP unvollständig oder Modellcache beschädigt", "Paket und SHA-256 neu prüfen; vollständiges betreutes Paket anfordern"],
        ["Backend startet nicht", "Gebündelte Backend-Laufzeit fehlt oder ist beschädigt", "Nicht am App-Inhalt reparieren; Support mit macOS-Version und Screenshot kontaktieren"],
        ["Start dauert sehr lang", "Erster Lauf oder Modellinitialisierung", "Bis zu 60 s warten; bei >90 s als Blocker melden"],
        ["App hängt beim Beenden", "Backend-Prozess beendet sich nicht", "Einige Sekunden warten; danach TransCom im Aktivitätsmonitor beenden"],
    ], widths=[38*mm, 61*mm, CONTENT_W-99*mm], font_size=7.1)
    p.h2("Hilfreiche Basisdaten")
    p.checklist("Mac-Modell und Chip, zum Beispiel MacBook Pro M3 Pro")
    p.checklist("macOS-Version")
    p.checklist("Name und Prüfsumme des Beta-Pakets")
    p.checklist("Dauer vom App-Start bis zur Fehlermeldung")
    p.checklist("Exakter Text oder Screenshot der Meldung")
    p.callout("Keine vertraulichen Logs teilen", "Screenshots und Pfade vor Versand auf Namen, Produktionsbezeichnungen und Zugangstoken prüfen.", "warn")
    p.finish()

    p = Page(c, 16, "Troubleshooting: Audio, Text, LAN")
    p.table([
        ["Symptom", "Prüfung", "Maßnahme"],
        ["Demo nicht auswählbar", "Demo-Pfad im Build fehlt", "Vollständiges Testpaket anfordern; alternativ eigene freigegebene Audiodatei wählen"],
        ["Datei spielt nicht hörbar", "Ausgabegerät, Lautstärke, Stumm", "macOS-Ausgabe prüfen; dennoch beobachten, ob Feed und Text laufen"],
        ["Kein Transkript", "Status aktiv? Sprache hörbar? VAD bekommt Pegel?", "10 s warten; richtige Quelle wählen; mit klarer Sprache testen"],
        ["Live-Gerät fehlt", "Erst nach App-Start verbunden?", "Eingänge neu laden; macOS-Mikrofonrecht und Kabel prüfen"],
        ["Loopback ohne Signal", "Player und TransCom auf demselben virtuellen Gerät?", "Player-Ausgang und TransCom-Eingang angleichen; DAW-Meter prüfen"],
        ["Text falsch/fragmentiert", "Überlappung, Lärm, kurze Calls, Fachbegriffe", "Nicht neu konfigurieren; Beispiel mit erwartet/erkannt und Zeit sichern"],
        ["Sprecher falsch", "Stimmprobe sauber und repräsentativ?", "Neu einsprechen; Zeile manuell korrigieren; als Beta-Risiko melden"],
        ["LAN-Link nicht erreichbar", "Gleiches LAN, Port 8787, VPN/Firewall", "VPN aus; lokale Netzwerkfreigabe prüfen; Link vollständig neu kopieren"],
        ["LAN meldet 403", "Token fehlt oder Freigabe wurde neu gestartet", "Aktuellen vollständigen Link aus der App verwenden"],
        ["Starter stoppt bei 60 s", "Anzeige Starter?", "Erwartetes Produktverhalten: Feed und Session sind beendet; neue Session anlegen"],
        ["Starter startet nicht erneut", "60-s-Budget derselben Session verbraucht?", "Eine neue Session anlegen; dadurch entsteht ein neues 60-s-Budget"],
        ["Export gesperrt", "Anzeige Starter bzw. Button Exportieren · Full?", "Erwartet in Starter; Export ist nur im getrennten Full-Build verfügbar"],
        ["Full-Exportdatei leer", "Richtige Session geöffnet? Segmente sichtbar?", "Session öffnen, Inhalt prüfen und erneut exportieren"],
    ], widths=[37*mm, 61*mm, CONTENT_W-98*mm], font_size=6.7)
    p.callout("Minimaler Reproduktionstest", "Neue Session - Demo starten - Ergebnis beobachten. Starter muss bei 60 s Feed und Session stoppen; danach neue Session anlegen. Full manuell stoppen und TXT exportieren. Erst danach Live-Routing untersuchen.", "info")
    p.finish()

    p = Page(c, 17, "Beta-Testcheckliste")
    p.h2("1. Installation")
    for item in ["Paket/Prüfsumme kontrolliert", "Starter-/Full-Dateiname und Anzeige stimmen überein", "App entpackt und geöffnet", "Audio-Engine wird bereit"]:
        p.checklist(item)
    p.h2("2. Demo und Datei")
    for item in ["Demo auswählbar", "Audio hörbar", "Erste Zeile nach ____ Sekunden", "Transkription beendet sauber", "Eigene Datei getestet: Format ______"]:
        p.checklist(item)
    p.h2("3. Livebetrieb")
    for item in ["Eingang erkannt: ____________________", "Start/Stop verständlich", "Starter: Stopp bei exakt 60 s / Full: 5 Minuten", "Überlappende Sprecher ausprobiert"]:
        p.checklist(item)
    p.h2("4. Ergebnis")
    p.table([
        ["Kriterium", "1 schlecht", "2", "3", "4", "5 gut"],
        ["Deutsch", "□", "□", "□", "□", "□"],
        ["Englisch", "□", "□", "□", "□", "□"],
        ["Fachbegriffe/Zahlen", "□", "□", "□", "□", "□"],
        ["Zeilengruppierung", "□", "□", "□", "□", "□"],
        ["Latenz", "□", "□", "□", "□", "□"],
        ["Sprecherzuordnung", "□", "□", "□", "□", "□"],
        ["Bedienbarkeit", "□", "□", "□", "□", "□"],
    ], widths=[60*mm] + [(CONTENT_W-60*mm)/5]*5)
    p.h2("5. Weitergabe")
    for item in ["Starter: Export sichtbar gesperrt", "Starter: neue Session nach 60 s möglich", "Full: TXT und CSV exportiert", "LAN-Viewer geöffnet und anschließend gestoppt"]:
        p.checklist(item)
    p.finish()

    p = Page(c, 18, "Feedback, das wirklich hilft")
    p.h2("Jeden relevanten Fehler so melden")
    p.table([
        ["Feld", "Eintrag"],
        ["Zeitstempel", "________________________"],
        ["Quelle", "□ Demo  □ Datei  □ Live  | Gerät/Datei: ____________________"],
        ["Sprache / Situation", "________________________________________________________"],
        ["Erwartet", "________________________________________________________"],
        ["Erkannt", "________________________________________________________"],
        ["Latenz", "erste Ausgabe ____ s | spätere Zeile ca. ____ s"],
        ["Mehrfachzeile?", "□ nein  □ ja | gleiche Segmentstelle: ____________________"],
        ["Audio verfügbar?", "□ freigegebener Ausschnitt  □ nein  □ vertraulich/nicht teilbar"],
        ["Schweregrad", "□ Blocker  □ schwer  □ störend  □ kosmetisch"],
    ], widths=[43*mm, CONTENT_W-43*mm])
    p.h2("Gesamtfazit")
    p.checklist("Ja, ich würde einen weiteren Test durchführen.")
    p.checklist("Nur mit Einschränkungen: ______________________________________________")
    p.checklist("Nein, weil: _________________________________________________________")
    p.gap(2*mm)
    p.para("Die drei wichtigsten Verbesserungen:")
    p.para("1. ______________________________________________________________________")
    p.para("2. ______________________________________________________________________")
    p.para("3. ______________________________________________________________________")
    p.callout("Priorisierung", "Ein reproduzierbarer Blocker mit Quelle, Zeitstempel und erwartet/erkannt ist wertvoller als viele allgemeine Eindrücke. Vertrauliche Inhalte bitte nicht ungeprüft mitsenden.", "teal")
    p.finish()

    p = Page(c, 19, "Technischer Anhang: betreutes Setup")
    p.callout("Nur für technisch betreute Installation", "Der ausgelieferte Desktop-Build bündelt Backend und Modelle und benötigt diese Quellinstallation nicht. Die folgenden Schritte gelten nur für Entwicklung und betreute Diagnose.", "warn")
    p.h2("Voraussetzungen")
    p.bullet("Apple-Silicon-Mac, Homebrew, Python 3.11+ empfohlen, Node/npm und mehrere GB freier Speicher.")
    p.bullet("Internetzugang ausschließlich für Installation/Modelldownload; Runtime danach offline.")
    p.h2("Setup und Start")
    p.code("cd \"<TransCom-Projektordner>\"\n./scripts/setup.sh\n./scripts/dev.sh")
    p.para("Alternativer Entwicklungsstart:", S_SMALL)
    p.code("npm run dev:renderer\nPYTHONUNBUFFERED=1 PYTHONPATH=\"$PWD\" \\\n  backend/.venv/bin/python backend/main.py")
    p.h2("Offline-Verifikation")
    p.code("HF_HUB_OFFLINE=1 backend/.venv/bin/python \\\n  scripts/download_models.py --verify-only")
    p.table([
        ["Rolle", "Gepinntes Modell"],
        ["Kurze Äußerungen bis 3,0 s", "mlx-community/whisper-large-v3-turbo-q4"],
        ["Längere Äußerungen", "mlx-community/whisper-large-v3-mlx-4bit"],
        ["Fallback / Safety-Zweitprüfung", "Systran/faster-whisper-small"],
    ], widths=[58*mm, CONTENT_W-58*mm])
    p.para("Getrennte Release-Builds werden technisch mit <b>npm run build:editions</b> erzeugt. Die Edition eines gepackten Builds stammt aus seinem Manifest und kann nicht über eine Umgebungsvariable freigeschaltet werden.", S_SMALL)
    p.h2("Letzte dokumentierte Verifikation")
    p.para("203 Python-Tests und 4 Renderer-Editionstests bestanden; alle drei exakten Modell-Snapshots und jede gebündelte Datei per SHA-256 offline bestätigt. Diese Verifikation ersetzt nicht den Smoke-Test beider Apps auf einem sauberen Apple-Silicon-Mac.")
    p.finish()

    p = Page(c, 20, "Kurzreferenz")
    p.h2("Die fünf wichtigsten Regeln")
    p.step(1, "Edition prüfen", "ZIP-Dateiname und Anzeige <b>Starter</b> oder <b>Full</b> müssen zusammenpassen.")
    p.step(2, "Starter neu anlegen", "Nach dem automatischen Stopp bei exakt 60 Sekunden eine neue Session für den nächsten Abschnitt erstellen.")
    p.step(3, "Audio bleibt maßgeblich", "Zahlen, Namen, Richtungen und Sicherheitskommunikation nie nur aus dem Transkript übernehmen.")
    p.step(4, "Nur vertrauenswürdiges LAN", "Desktop-Auth-Bypass und unverschlüsselten LAN-Viewer nicht in fremden Netzen einsetzen.")
    p.step(5, "Beispiele statt Bauchgefühl", "Zeitstempel, Quelle, erwartet/erkannt und Latenz dokumentieren.")
    p.h2("Bedienkürzel")
    p.table([
        ["Ziel", "Weg in der App"],
        ["Demo starten", "Links: Demo - Transkription starten"],
        ["Eigene Datei", "Links: Datei - auswählen - starten"],
        ["Live-Eingang", "Links: Live - Audioeingang - starten"],
        ["Export", "Nur Full: links oben Exportieren - TXT/CSV"],
        ["Stimmen", "Optionen - Stimmen erkennen"],
        ["LAN-Viewer", "Optionen - Live-Ansicht teilen - Link erzeugen"],
        ["Alte Session", "Rechts: Gespeicherte Transkripte - Öffnen"],
    ], widths=[45*mm, CONTENT_W-45*mm])
    p.callout("Beta-Ziel erreicht, wenn ...", "Installation und Demo reproduzierbar laufen, Starter exakt bei 60 Sekunden stoppt und eine neue Session erlaubt, Full ohne diese Grenze arbeitet, Full-Exporte entstehen und Qualitätsgrenzen konkret dokumentiert sind.", "good")
    p.para("Dokumentstatus: Inhaltlich gegen Quellcode, Setup und Handoff vom 14.07.2026 geprüft. Das Handbuch beschreibt den tatsächlichen Beta-Stand einschließlich offener Release-Risiken.", S_SMALL)
    p.finish()

    c.save()
    return OUT


if __name__ == "__main__":
    print(build())
