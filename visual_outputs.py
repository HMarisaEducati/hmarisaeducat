"""Visual output renderers for TPQ HMarisa.

The preview image and downloadable PDF use the same rendered PNG so the visual
layout cannot diverge between browser preview and PDF output.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont

DARK_GREEN = "#064D3A"
GREEN = "#075F46"
GOLD = "#B78324"
GOLD_LIGHT = "#D8A72E"
CREAM = "#FFFDF7"
TEXT = "#123C31"
GRID = "#A9B8B3"
MUTED = "#4C625A"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = [
        "/usr/share/fonts/truetype/lato/Lato-Bold.ttf" if bold else "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
        "/usr/share/fonts/opentype/inter/Inter-Bold.otf" if bold else "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, min_size: int = 12, bold: bool = False):
    size = start_size
    while size > min_size:
        font = _font(size, bold)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 1
    return _font(min_size, bold)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int | None = None) -> list[str]:
    words = (text or "").replace("\n", " \n ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        if word == "\\n":
            if current:
                lines.append(current)
                current = ""
            continue
        candidate = word if not current else f"{current} {word}"
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if max_lines and len(lines) >= max_lines:
            break
    if current and (not max_lines or len(lines) < max_lines):
        lines.append(current)
    if max_lines and len(lines) == max_lines:
        joined = " ".join(words)
        visible = " ".join(lines)
        if len(visible) < len(joined):
            last = lines[-1]
            while last and draw.textbbox((0, 0), last + "…", font=font)[2] > max_width:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"
    return lines


def _draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont,
                  max_width: int, fill: str = TEXT, line_gap: int = 4, max_lines: int | None = None,
                  align: str = "left") -> int:
    x, y = xy
    lines = _wrap(draw, text, font, max_width, max_lines=max_lines)
    line_height = (draw.textbbox((0, 0), "Ag", font=font)[3] + line_gap)
    for line in lines:
        if align == "center":
            width = draw.textbbox((0, 0), line, font=font)[2]
            dx = x + (max_width - width) / 2
        else:
            dx = x
        draw.text((dx, y), line, font=font, fill=fill)
        y += line_height
    return y


def _rounded_patch(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int = 18,
                   fill: str = CREAM, outline: str | None = None, width: int = 1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def render_monthly_poster(template_path: str, winners: Iterable[dict[str, Any]], month_label: str,
                          output_path: str | None = None, settings: dict[str, Any] | None = None) -> BytesIO | str:
    """Render poster bulanan memakai artwork hijau-emas yang disetujui.

    Template lama tetap digunakan agar seluruh ornamen dan komposisi tidak berubah.
    Tulisan "Minggu Ini" diganti menjadi "Bulan <nama bulan> <tahun>", sedangkan
    nama pemenang pada tiga kelas diisi otomatis tanpa foto asli santri.
    """
    settings = settings or {}
    dynamic = bool(settings.get("enabled"))
    title_color = str(settings.get("title_color") or "#C58805") if dynamic else "#C58805"
    title_shadow = str(settings.get("title_shadow") or "#7B5715") if dynamic else "#7B5715"
    name_color = str(settings.get("name_color") or DARK_GREEN) if dynamic else DARK_GREEN
    card_fill = str(settings.get("card_fill") or "#FCFAF3") if dynamic else "#FCFAF3"
    period_prefix = str(settings.get("period_prefix") or "Bulan") if dynamic else "Bulan"
    class_prefix = str(settings.get("class_prefix") or "Kelas") if dynamic else "Kelas"

    image = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    sx, sy = width / 1122.0, height / 1402.0

    def X(v: float) -> int:
        return int(v * sx)

    def Y(v: float) -> int:
        return int(v * sy)

    winner_map = {
        str(item.get("class_name") or "").strip(): str(item.get("name") or "Belum ditetapkan").strip()
        for item in winners
    }

    # Bersihkan hanya area subjudul lama "Minggu Ini". Judul utama, logo,
    # ornamen, dan banner TPQ HMarisa tetap mengikuti desain asli.
    title_box = (X(295), Y(430), X(830), Y(524))
    draw.rounded_rectangle(title_box, radius=X(18), fill=card_fill)
    title = f"{period_prefix} {month_label}"
    title_font = _fit_font(draw, title, X(505), X(54), min_size=X(34), bold=True)
    box = draw.textbbox((0, 0), title, font=title_font, stroke_width=max(1, X(3)))
    tw = box[2] - box[0]
    tx = X(562) - tw / 2
    ty = Y(438)
    draw.text((tx + X(3), ty + Y(4)), title, font=title_font, fill=title_shadow,
              stroke_width=max(1, X(4)), stroke_fill="#FFFFFF")
    draw.text((tx, ty), title, font=title_font, fill=title_color,
              stroke_width=max(1, X(4)), stroke_fill="#FFFFFF")

    cards = [
        {"class": "Ar Rahman", "box": (450, 657, 850, 765), "label_y": 674, "name_y": 712},
        {"class": "Ar Rahim", "box": (450, 786, 850, 894), "label_y": 803, "name_y": 841},
        {"class": "Al-Bayyan", "box": (450, 915, 850, 1025), "label_y": 932, "name_y": 970},
    ]

    for card in cards:
        x0, y0, x1, y1 = card["box"]
        draw.rectangle((X(x0), Y(y0), X(x1), Y(y1)), fill=card_fill)
        class_label = f"{class_prefix} {card['class']}:"
        label_font = _fit_font(draw, class_label, X(x1 - x0 - 24), X(29), min_size=X(21), bold=True)
        draw.text((X(x0 + 12), Y(card["label_y"])), class_label, font=label_font, fill=name_color)

        name = winner_map.get(card["class"], "Belum ditetapkan") or "Belum ditetapkan"
        name_font = _fit_font(draw, name, X(x1 - x0 - 24), X(42), min_size=X(23), bold=True)
        draw.text((X(x0 + 12), Y(card["name_y"])), name, font=name_font, fill=name_color)

    if output_path:
        image.save(output_path, "PNG", optimize=True)
        return output_path
    buffer = BytesIO()
    image.save(buffer, "PNG", optimize=True)
    buffer.seek(0)
    return buffer


def render_weekly_poster(template_path: str, winners: Iterable[dict[str, Any]], output_path: str | None = None) -> BytesIO | str:
    """Alias kompatibilitas untuk instalasi lama; menghasilkan poster bulanan."""
    return render_monthly_poster(template_path, winners, "Ini", output_path)


def render_report_image(template_path: str, data: dict[str, Any], output_path: str | None = None) -> BytesIO | str:
    """Render one-page raport using the approved report artwork as the base.

    Dynamic fields are redrawn on top of the artwork. This exact PNG is used by
    both browser preview and PDF generation, guaranteeing matching layouts.
    """
    image = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    sx, sy = width / 1054.0, height / 1492.0

    def X(v: float) -> int: return int(v * sx)
    def Y(v: float) -> int: return int(v * sy)
    def rect(box, fill="#FFFFFF", outline=None, radius=0, line_width=1):
        b = (X(box[0]), Y(box[1]), X(box[2]), Y(box[3]))
        if radius:
            draw.rounded_rectangle(b, radius=X(radius), fill=fill, outline=outline, width=max(1, X(line_width)))
        else:
            draw.rectangle(b, fill=fill, outline=outline, width=max(1, X(line_width)))
        return b
    def font(size: int, bold: bool = False): return _font(max(10, X(size)), bold)
    def text(x, y, value, size=17, bold=False, fill=TEXT, max_width=None, center=False):
        value = str(value if value not in (None, "") else "-")
        f = font(size, bold)
        if max_width:
            f = _fit_font(draw, value, X(max_width), X(size), min_size=X(10), bold=bold)
        if center:
            bbox = draw.textbbox((0, 0), value, font=f)
            x = x - (bbox[2] - bbox[0]) / 2 / sx
        draw.text((X(x), Y(y)), value, font=f, fill=fill)

    # Year banner: replace only the centered variable text.
    rect((337, 188, 685, 228), fill=GREEN)
    text(511, 195, f"Tahun Ajaran {data.get('academic_year','2026/2027')}", 18, True, "#FFFFFF", max_width=320, center=True)

    # Identity values.
    identity_fill = "#FFFDF9"
    rect((268, 279, 485, 398), fill=identity_fill)
    rect((708, 279, 944, 398), fill=identity_fill)
    text(278, 286, data.get("student_name", "-"), 17, False, "#172B26", max_width=195)
    text(278, 325, data.get("nis", "-"), 17, False, "#172B26", max_width=195)
    text(278, 363, data.get("class_name", "-"), 17, False, "#172B26", max_width=195)
    text(720, 286, data.get("semester", "Semester 1"), 17, False, "#172B26", max_width=210)
    text(720, 341, data.get("academic_year", "2026/2027"), 17, False, "#172B26", max_width=210)

    # Clear the dynamic central report area so no sample data from the artwork leaks through.
    rect((54, 417, 990, 1444), fill="#FFFEFB")

    def panel(box, title, title_width=None):
        x0,y0,x1,y1=box
        rect(box, fill="#FFFEFB", outline="#C79B43", radius=13, line_width=1)
        tw = title_width or min(360, x1-x0-28)
        rect((x0+5,y0-2,x0+5+tw,y0+40), fill=GREEN, outline="#C79B43", radius=10, line_width=1)
        text(x0+22,y0+8,title,16,True,"#FFFFFF",max_width=tw-34)

    # NILAI AKADEMIK
    panel((60, 424, 962, 660), "NILAI AKADEMIK", 300)
    table_left, table_top, table_right, table_bottom = 68, 472, 952, 642
    header_h = 34
    draw.rectangle((X(table_left),Y(table_top),X(table_right),Y(table_top+header_h)),fill=GREEN)
    cols=[68,122,430,562,725,952]
    headers=["No.","Mata Pelajaran","Nilai","Predikat","Keterangan"]
    for c in cols[1:-1]:
        draw.line((X(c),Y(table_top),X(c),Y(table_bottom)),fill="#8FA09A",width=max(1,X(1)))
    draw.line((X(table_left),Y(table_top+header_h),X(table_right),Y(table_top+header_h)),fill="#8FA09A",width=max(1,X(1)))
    for (x0,x1),value in zip(zip(cols[:-1],cols[1:]),headers):
        f=_fit_font(draw,value,X(x1-x0-8),X(13),min_size=X(9),bold=True)
        bb=draw.textbbox((0,0),value,font=f)
        draw.text((X((x0+x1)/2)-(bb[2]-bb[0])/2,Y(table_top+8)),value,font=f,fill="#FFFFFF")
    subjects=list(data.get("subjects") or [])
    scores=data.get("scores") or {}
    row_count=max(1,len(subjects))
    body_top=table_top+header_h
    row_h=(table_bottom-body_top)/row_count
    for i in range(1,row_count):
        yy=body_top+i*row_h
        draw.line((X(table_left),Y(yy),X(table_right),Y(yy)),fill="#A9B8B3",width=max(1,X(1)))
    body_size=14 if row_count<=5 else 11
    for idx,subject in enumerate(subjects,1):
        y0=body_top+(idx-1)*row_h
        raw=scores.get(subject)
        shown="Belum diisi" if raw in (None,"",0,"0") else str(raw)
        pred,note,_status=_predicate(raw)
        vals=[str(idx),subject,shown,pred or "-",note]
        for ci,(x0,x1,val) in enumerate(zip(cols[:-1],cols[1:],vals)):
            f=_fit_font(draw,str(val),X(x1-x0-10),X(body_size),min_size=X(8),bold=False)
            bb=draw.textbbox((0,0),str(val),font=f)
            xx=X((x0+x1)/2)-(bb[2]-bb[0])/2 if ci in (0,2,3) else X(x0+8)
            yy=Y(y0)+(Y(row_h)-(bb[3]-bb[1]))/2-bb[1]
            draw.text((xx,yy),str(val),font=f,fill="#172B26")

    # PROGRES HAFALAN JUZ 30
    panel((60, 680, 962, 805), "PROGRES HAFALAN JUZ 30", 340)
    done=int(data.get("hafalan_done") or 0)
    total=int(data.get("hafalan_total") or 37)
    percent=round((done/total*100) if total else 0)
    text(95,735,f"{done} dari {total} surah",17,False,"#142D27")
    track=(92,768,460,786)
    _rounded_patch(draw,(X(track[0]),Y(track[1]),X(track[2]),Y(track[3])),radius=X(9),fill="#DDE8DF")
    fill_right=track[0]+(track[2]-track[0])*max(0,min(100,percent))/100
    if percent>0:
        _rounded_patch(draw,(X(track[0]),Y(track[1]),X(fill_right),Y(track[3])),radius=X(9),fill=GREEN)
    rect((488,748,550,786),fill=GREEN,radius=8)
    text(519,756,f"{percent}%",16,True,"#FFFFFF",max_width=55,center=True)
    rect((582,699,930,786),fill="#FBF4E7",radius=12)
    _draw_wrapped(draw,(X(670),Y(716)),"Teruslah menghafal, setiap huruf yang kau simpan adalah cahaya di dunia dan akhirat.",font(13,False),X(230),fill="#172B26",line_gap=2,max_lines=4)

    # CATATAN PERKEMBANGAN
    panel((60, 826, 474, 1058), "CATATAN PERKEMBANGAN", 410)
    notes=data.get("development_notes") or "Belum diisi"
    _draw_wrapped(draw,(X(80),Y(880)),notes,font(14,False),X(370),fill="#172B26",line_gap=2,max_lines=5)
    rect((82,976,452,1042),fill="#FBF4E7",radius=10)
    quote='“Barang siapa yang menempuh jalan untuk mendapatkan ilmu, maka Allah akan mudahkan baginya jalan menuju surga.” (HR. Muslim)'
    _draw_wrapped(draw,(X(100),Y(987)),quote,font(11,False),X(335),fill=TEXT,line_gap=1,max_lines=4,align="center")

    # KETUNTASAN KKM
    panel((498, 826, 962, 956), "KETUNTASAN KKM", 305)
    text(730,881,"KKM (Kriteria Ketuntasan Minimal)",14,True,TEXT,max_width=410,center=True)
    text(730,914,str(data.get("kkm",70)),31,True,GREEN,center=True)

    # KETIDAKHADIRAN / ABSEN
    panel((60, 1074, 474, 1228), "KETIDAKHADIRAN / ABSEN", 330)
    abs_left,abs_top,abs_right,abs_bottom=68,1118,466,1219
    abs_cols=[68,243,335,466]
    hh=24
    draw.rectangle((X(abs_left),Y(abs_top),X(abs_right),Y(abs_top+hh)),fill="#F7F0DF")
    for c in abs_cols[1:-1]: draw.line((X(c),Y(abs_top),X(c),Y(abs_bottom)),fill="#A9B8B3",width=max(1,X(1)))
    draw.line((X(abs_left),Y(abs_top+hh),X(abs_right),Y(abs_top+hh)),fill="#A9B8B3",width=max(1,X(1)))
    for (x0,x1),val in zip(zip(abs_cols[:-1],abs_cols[1:]),["Alasan Ketidakhadiran","Jumlah","Keterangan"]):
        f=_fit_font(draw,val,X(x1-x0-6),X(10),min_size=X(7),bold=True); bb=draw.textbbox((0,0),val,font=f)
        draw.text((X((x0+x1)/2)-(bb[2]-bb[0])/2,Y(abs_top+5)),val,font=f,fill=TEXT)
    absence=data.get("absence") or {}
    abs_keys=["Sakit","Izin","Tanpa Keterangan","Keterangan Lain"]
    rh=(abs_bottom-abs_top-hh)/4
    for i,key in enumerate(abs_keys):
        y0=abs_top+hh+i*rh
        if i: draw.line((X(abs_left),Y(y0),X(abs_right),Y(y0)),fill="#A9B8B3",width=max(1,X(1)))
        item=absence.get(key,{}) if isinstance(absence.get(key,{}),dict) else {}
        vals=[key,str(item.get("count",0)),item.get("notes") or "-"]
        for ci,(x0,x1,val) in enumerate(zip(abs_cols[:-1],abs_cols[1:],vals)):
            f=_fit_font(draw,str(val),X(x1-x0-6),X(10),min_size=X(7),bold=False); bb=draw.textbbox((0,0),str(val),font=f)
            xx=X((x0+x1)/2)-(bb[2]-bb[0])/2 if ci==1 else X(x0+6)
            yy=Y(y0)+(Y(rh)-(bb[3]-bb[1]))/2-bb[1]
            draw.text((xx,yy),str(val),font=f,fill="#172B26")

    # PENILAIAN SIKAP
    panel((498, 972, 962, 1228), "PENILAIAN SIKAP", 300)
    att_left,att_top,att_right,att_bottom=506,1016,954,1219
    att_cols=[506,695,806,954]
    hh=31
    for c in att_cols[1:-1]: draw.line((X(c),Y(att_top),X(c),Y(att_bottom)),fill="#A9B8B3",width=max(1,X(1)))
    draw.line((X(att_left),Y(att_top+hh),X(att_right),Y(att_top+hh)),fill="#A9B8B3",width=max(1,X(1)))
    for (x0,x1),val in zip(zip(att_cols[:-1],att_cols[1:]),["Sikap","Nilai","Predikat"]):
        f=font(12,True); bb=draw.textbbox((0,0),val,font=f)
        draw.text((X((x0+x1)/2)-(bb[2]-bb[0])/2,Y(att_top+7)),val,font=f,fill=TEXT)
    att=data.get("attitude") or {}; labels={"A":"Sangat Baik","B":"Baik","C":"Cukup","D":"Perlu Bimbingan"}
    keys=["Kehadiran","Kedisiplinan","Keterlibatan","Pergaulan/Perilaku"]
    rh=(att_bottom-att_top-hh)/4
    for i,key in enumerate(keys):
        y0=att_top+hh+i*rh
        if i: draw.line((X(att_left),Y(y0),X(att_right),Y(y0)),fill="#A9B8B3",width=max(1,X(1)))
        val=att.get(key) or "-"; vals=[key,val,labels.get(val,"Belum diisi")]
        for x0,x1,v in zip(att_cols[:-1],att_cols[1:],vals):
            f=_fit_font(draw,str(v),X(x1-x0-8),X(11),min_size=X(8),bold=False); bb=draw.textbbox((0,0),str(v),font=f)
            xx=X((x0+x1)/2)-(bb[2]-bb[0])/2; yy=Y(y0)+(Y(rh)-(bb[3]-bb[1]))/2-bb[1]
            draw.text((xx,yy),str(v),font=f,fill="#172B26")

    # Signature panel
    rect((60,1238,962,1412),fill="#FFFFFF",outline="#C79B43",radius=12,line_width=1)
    sep1,sep2=335,650
    for xx in (sep1,sep2):
        yy=1252
        while yy<1400:
            draw.line((X(xx),Y(yy),X(xx),Y(min(yy+5,1400))),fill="#7D9189",width=max(1,X(1))); yy+=10
    principal=data.get("principal") or "Bunda Hj. Maryamah, S.Ag"; teacher=data.get("teacher") or "-"; publish_date=data.get("publish_date") or "-"; cls=data.get("class_name") or "-"
    text(198,1258,"Mengetahui,",13,False,TEXT,center=True); text(198,1280,"Kepala TPQ HMarisa",13,False,TEXT,center=True); text(198,1370,principal,12,True,TEXT,max_width=250,center=True)
    draw.line((X(92),Y(1393),X(304),Y(1393)),fill=TEXT,width=max(1,X(1)))
    text(492,1250,f"Tangerang Selatan, {publish_date}",12,False,TEXT,max_width=285,center=True); text(492,1274,"Wali Kelas",13,False,TEXT,center=True); text(492,1296,cls,12,False,TEXT,max_width=250,center=True); text(492,1370,teacher,12,True,TEXT,max_width=275,center=True)
    draw.line((X(365),Y(1393),X(620),Y(1393)),fill=TEXT,width=max(1,X(1)))
    text(805,1270,"Orang Tua / Wali Santri",13,False,TEXT,max_width=280,center=True); text(805,1374,"(........................................)",12,False,TEXT,center=True)

    # Footer address.
    rect((165, 1444, 894, 1480), fill=GREEN)
    address = data.get("address") or "Jl. Kayu Gede 2, Paku Jaya, Kec. Serpong Utara, Kota Tangerang, Banten 15220"
    text(529,1454,address,11,False,"#FFFFFF",max_width=700,center=True)

    # Draft status is shown outside the artwork so preview and PDF remain identical.

    if output_path:
        image.save(output_path, "PNG", optimize=True)
        return output_path
    buffer = BytesIO()
    image.save(buffer, "PNG", optimize=True)
    buffer.seek(0)
    return buffer


def _predicate(value: Any) -> tuple[str, str, str]:
    if value in (None, "", 0, "0"):
        return "", "Belum diisi", ""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "", "Belum diisi", ""
    if number >= 91:
        return "A", "Sangat Baik", "Tuntas"
    if number >= 81:
        return "B", "Baik", "Tuntas"
    if number >= 71:
        return "C", "Cukup", "Tuntas"
    return "D", "Perlu Bimbingan", "Tuntas" if number >= 70 else "Belum Tuntas"
