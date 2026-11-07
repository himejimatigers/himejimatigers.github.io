#!/usr/bin/env python3
"""姫島タイガース公式サイトのビルドスクリプト（5ページ構成版）

site-src/templates/ にある完成版HTML（中身の差し込み口つき）に、
Pages CMS で編集する content/ のデータを差し込み、_site/ に公開用ファイルを書き出します。

- デザイン（HTML/CSS/画像）はテンプレートに完成版のまま入っており、このスクリプトは変更しません。
- 差し込む部分のHTMLは、完成版と同じタグ・クラス名で出力します。
- Python標準ライブラリだけで動きます（追加インストール不要）。

使い方:  python3 site-src/build.py            → _site/ に出力
         python3 site-src/build.py OUTDIR     → 指定フォルダに出力
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import json
import mimetypes
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site-src"
TEMPLATES = SRC / "templates"
CONTENT = ROOT / "content"
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "_site"

PAGES = ["index.html", "news.html", "results.html", "schedule.html", "staff.html"]
COPY_AS_IS = ["header-tigers-logo.png", "tigers-logo.png"]
TOP_LIMIT = 3  # トップページに出す件数
JST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.datetime.now(JST).date().isoformat()

EMPTY_INFO = '<p class="empty">現在、公開中の情報はありません。最新情報はInstagramをご覧ください。</p>'
EMPTY_GALLERY = '<p class="empty">写真は準備中です。掲載許可を確認した写真から公開します。</p>'
PLACEHOLDER_SVG = ('<div class="staff-placeholder"><svg aria-hidden="true" fill="none" stroke="currentColor" '
                   'stroke-width="2.5" viewbox="0 0 64 64"><circle cx="32" cy="20" r="11"></circle>'
                   '<path d="M11 57c0-13 9-21 21-21s21 8 21 21"></path></svg><span>PHOTO COMING SOON</span></div>')


# ------------------------------------------------------------------ helpers
def t(value) -> str:
    """本文用のエスケープ（& < > のみ）。"""
    return html.escape("" if value is None else str(value), quote=False)


def a(value) -> str:
    """属性値用のエスケープ。"""
    return html.escape("" if value is None else str(value), quote=True)


def lines_br(value) -> str:
    """改行を <br/> に。"""
    return "<br/>".join(t(x) for x in str(value or "").replace("\r\n", "\n").split("\n"))


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise SystemExit(f"データの書式エラー: {path.relative_to(ROOT)}: {e}")


def collection(name: str) -> list[dict]:
    folder = CONTENT / name
    rows = []
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        row = load_json(f, {})
        if isinstance(row, dict) and row.get("published", True) is not False:
            row["_file"] = f.name
            rows.append(row)
    return rows


def media_path(path: str) -> Path | None:
    """CMSの画像パス（/media/... ）をリポジトリ内のファイルに。安全でないパスは無視。"""
    p = str(path or "").strip()
    if not p or ".." in p or "\\" in p or re.match(r"^[a-z]+:", p, re.I):
        return None
    f = (ROOT / p.lstrip("/")).resolve()
    if ROOT not in f.parents or not f.is_file():
        return None
    return f


_data_uri_cache: dict[Path, str] = {}

# スマホで撮った大きな写真をそのまま載せるとページが重くなるため、
# この大きさを超える写真だけ、公開用に縮小した複製を使う（元の写真ファイルは変更しない）。
# 現在掲載中の写真はすべてこれより小さいので、そのままの画質で載る。
MAX_BYTES = 600 * 1024
MAX_EDGE = 1600


def web_bytes(f: Path) -> tuple[bytes, str]:
    data = f.read_bytes()
    mime = mimetypes.guess_type(f.name)[0] or "image/jpeg"
    if len(data) <= MAX_BYTES:
        return data, mime
    try:
        from io import BytesIO
        from PIL import Image, ImageOps
    except ImportError:  # Pillow が無い環境では元のまま使う
        return data, mime
    try:
        im = ImageOps.exif_transpose(Image.open(BytesIO(data)))
        im.thumbnail((MAX_EDGE, MAX_EDGE))
        buf = BytesIO()
        if im.mode in ("RGBA", "LA", "P") and mime == "image/png":
            im.save(buf, "PNG", optimize=True)
            out_mime = "image/png"
        else:
            im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True, progressive=True)
            out_mime = "image/jpeg"
        small = buf.getvalue()
        return (small, out_mime) if len(small) < len(data) else (data, mime)
    except Exception as e:  # 壊れた画像などは元のまま
        print(f"  注意: {f.name} を縮小できませんでした（{e}）。元の写真を使います。")
        return data, mime


def data_uri(path: str) -> str | None:
    f = media_path(path)
    if not f:
        return None
    if f not in _data_uri_cache:
        data, mime = web_bytes(f)
        _data_uri_cache[f] = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
    return _data_uri_cache[f]


def date_key(row: dict) -> str:
    return str(row.get("date") or "")[:10]


# ------------------------------------------------------------------ renderers
def render_about(site: dict) -> str:
    ab = site.get("about", {})
    return (f'<p class="about-text">{t(ab.get("description"))}</p>'
            f'<p>活動エリア：{t(ab.get("area"))}</p><p>対象：{t(ab.get("target"))}</p>')


def render_policies(site: dict) -> str:
    out = []
    for i, p in enumerate(site.get("policies") or [], 1):
        out.append(f'<article class="feature"><b>{i:02d}</b><h3>{t(p.get("title"))}</h3><p>{t(p.get("text"))}</p></article>')
    return "".join(out)


def staff_rows() -> list[dict]:
    rows = collection("staff")
    rows.sort(key=lambda r: (float(r.get("order") or 9999), r["_file"]))
    for n, r in enumerate(rows, 1):
        r["_n"] = n
        r["_photo"] = data_uri(r.get("photo"))
        r["_name"] = r.get("name") or "名前は準備中"
        r["_comment"] = r.get("comment") or "紹介コメントは準備中です。"
    return rows


def render_staff_card(r: dict) -> str:
    if r["_photo"]:
        photo = (f'<a aria-label="{a(r["_name"])}のプロフィールと写真を見る" class="staff-photo-trigger" href="#staff-profile-{r["_n"]}">'
                 f'<img alt="{a(r["_name"])}の写真" loading="lazy" src="{r["_photo"]}"/>'
                 '<span class="staff-photo-hint">写真・プロフィールを見る ↗</span></a>')
    else:
        photo = PLACEHOLDER_SVG
    return (f'<article class="staff-card"><div class="staff-photo">{photo}</div><div class="staff-card-body">'
            f'<div class="staff-role">{t(r.get("role"))}</div><h3 class="staff-name">{t(r["_name"])}</h3>'
            f'<p class="staff-comment">{t(r["_comment"])}</p></div></article>')


def render_staff_block(site: dict, rows: list[dict], limit: int | None) -> str:
    cards = "".join(render_staff_card(r) for r in (rows[:limit] if limit else rows))
    return f'<p class="staff-lead">{t(site.get("staff_lead"))}</p><div class="staff-grid" id="staff-grid">{cards}</div>'


def render_overlays(rows: list[dict]) -> str:
    out = []
    for r in rows:
        if not r["_photo"]:
            continue
        out.append(f'<div aria-label="{a(r["_name"])}のプロフィール" class="staff-profile-overlay" id="staff-profile-{r["_n"]}" role="dialog">'
                   '<a aria-label="閉じる" class="staff-profile-shade" href="#staff"></a><div class="staff-profile-panel">'
                   '<a aria-label="閉じる" class="staff-profile-close" href="#staff">×</a><div class="staff-profile-photos">'
                   f'<img alt="{a(r["_name"])}の写真" loading="lazy" src="{r["_photo"]}"/></div><div class="staff-profile-info">'
                   f'<div class="staff-role">{t(r.get("role"))}</div><h3>{t(r["_name"])}</h3><p>{t(r["_comment"])}</p></div></div></div>')
    return "".join(out)


def news_rows() -> list[dict]:
    rows = collection("news")
    rows.sort(key=lambda r: (date_key(r), r["_file"]), reverse=True)
    return rows


def render_news(rows: list[dict]) -> str:
    if not rows:
        return EMPTY_INFO
    out = []
    for r in rows:
        body = f'<p>{lines_br(r.get("body"))}</p>' if r.get("body") else ""
        out.append(f'<article class="content-card"><time class="muted">{t(date_key(r))}</time>'
                   f'<h3>{t(r.get("title"))}</h3>{body}</article>')
    return "".join(out)


def schedule_rows() -> list[dict]:
    rows = [r for r in collection("schedule") if date_key(r) >= TODAY]  # 終わった予定は出さない
    rows.sort(key=lambda r: (date_key(r), str(r.get("time") or ""), r["_file"]))
    return rows


def render_schedule(rows: list[dict], site: dict) -> str:
    out = []
    for r in rows:
        when = date_key(r) + (f'　{r["time"]}' if r.get("time") else "")
        place = f'<p><strong>場所：</strong>{t(r.get("location"))}</p>' if r.get("location") else ""
        body = f'<p>{lines_br(r.get("body"))}</p>' if r.get("body") else ""
        out.append(f'<article class="content-card"><time class="muted">{t(when)}</time>'
                   f'<h3>{t(r.get("title"))}</h3>{place}{body}</article>')
    items = "".join(out) if out else EMPTY_INFO
    note = site.get("schedule_note")
    return items + (f'<p class="muted">{t(note)}</p>' if note else "")


# --- 試合結果（スコアボード）
OUR_TEAM = "姫島タイガース"


def split_innings(value) -> list[str]:
    if isinstance(value, list):
        cells = [str(x).strip() for x in value]
    else:
        cells = [x.strip() for x in re.split(r"[,，、\s]+", str(value or "")) if x.strip()]
    return cells


def cell_html(cell: str) -> str:
    m = re.match(r"^(\d+)([xX])$", cell)
    if m:
        return f'{m[1]}<span class="scoreboard-walkoff">x</span>'
    return t(cell)


def total_of(cells: list[str]) -> tuple[int, bool]:
    total, walkoff = 0, False
    for c in cells:
        m = re.match(r"^(\d+)([xX]?)$", c)
        if m:
            total += int(m[1])
            walkoff = walkoff or bool(m[2])
    return total, walkoff


def games_rows() -> list[dict]:
    rows = collection("games")
    # 試合日が新しい順。試合日が未入力のものは「表示順」の小さい順で後ろに並べる。
    dated = sorted([r for r in rows if date_key(r)], key=lambda r: (date_key(r), r["_file"]), reverse=True)
    undated = sorted([r for r in rows if not date_key(r)], key=lambda r: (float(r.get("order") or 9999), r["_file"]))
    return dated + undated


def render_game(r: dict) -> str:
    title = r.get("title") or ""
    teams = [r.get("top") or {}, r.get("bottom") or {}]
    cells = [split_innings(x.get("innings")) for x in teams]
    n = max(len(cells[0]), len(cells[1]), 1)
    for c in cells:
        c += [""] * (n - len(c))
    totals = [total_of(c) for c in cells]
    head = "".join(f'<th scope="col">{i}</th>' for i in range(1, n + 1))
    body = ""
    for team, c, (tot, wo) in zip(teams, cells, totals):
        tds = "".join(f"<td>{cell_html(x)}</td>" for x in c)
        tot_html = f'{tot}<span class="scoreboard-walkoff">x</span>' if wo else str(tot)
        body += f'<tr><th scope="row">{t(team.get("name"))}</th>{tds}<td class="scoreboard-total">{tot_html}</td></tr>'
    # 下段のスコアは「姫島タイガース − 相手」。どちらも姫島でなければ 先攻 − 後攻。
    ours = 1 if OUR_TEAM in str(teams[1].get("name")) and OUR_TEAM not in str(teams[0].get("name")) else 0
    fmt = lambda i: f"{totals[i][0]}" + ("x" if totals[i][1] else "")
    line = f"{fmt(ours)} − {fmt(1 - ours)}"
    caption = r.get("caption") or (
        f"{title}。" + "".join(f"{x.get('name')}は合計{tt}点。" for x, (tt, _) in zip(teams, totals)))
    table_label = r.get("table_label") or f"{title}のイニング別スコア表"
    status = r.get("status") or "試合終了"
    result = f'<span>{t(r.get("result_label"))}</span>' if r.get("result_label") else ""
    note = f'\n<p class="scoreboard-note">※ {t(r.get("note"))}</p>' if r.get("note") else ""
    return (f'<article aria-label="{a(title)}の試合結果" class="scoreboard">\n'
            f'<div class="scoreboard-top"><span class="scoreboard-league">{t(title)}</span>'
            f'<span class="scoreboard-finished">● {t(status)}</span></div>\n'
            f'<div aria-label="{a(table_label)}" class="scoreboard-scroll" role="region" tabindex="0">\n'
            f'<table class="scoreboard-table"><colgroup><col style="width:155px"/><col span="{n}"/><col style="width:64px"/></colgroup>'
            f'<caption class="sr-only">{t(caption)}</caption><thead><tr><th scope="col">TEAM</th>{head}'
            f'<th class="scoreboard-total" scope="col">計</th></tr></thead>\n<tbody>{body}</tbody></table></div>\n'
            f'<div class="scoreboard-bottom"><strong>{t(line)}</strong>{result}</div>{note}\n</article>')


def render_games(rows: list[dict]) -> str:
    return "".join(render_game(r) for r in rows) if rows else EMPTY_INFO


def render_gallery() -> tuple[str, list[Path]]:
    rows = collection("gallery")
    rows.sort(key=lambda r: (date_key(r), r["_file"]), reverse=True)
    out, files = [], []
    for r in rows[:12]:
        f = media_path(r.get("image"))
        if not f:
            continue
        rel = f.relative_to(ROOT).as_posix()
        files.append(f)
        cap = f'<figcaption class="muted">{t(r.get("title"))}</figcaption>' if r.get("title") else ""
        out.append(f'<figure style="margin:0"><img alt="{a(r.get("alt") or r.get("title") or "活動写真")}" class="photo" '
                   f'loading="lazy" src="{a(rel)}"/>{cap}</figure>')
    return ("".join(out) if out else EMPTY_GALLERY), files


def render_contact(site: dict) -> str:
    c = site.get("contact", {})
    return (f'<h2>{t(c.get("title"))}</h2><p class="recruit-lead">{t(c.get("lead"))}</p>'
            f'<p>{lines_br(c.get("body"))}</p>')


def render_requirements(site: dict) -> str:
    r = site.get("requirements", {})
    items = "".join(f'<div><dt>{t(x.get("label"))}</dt><dd>{t(x.get("value"))}</dd></div>' for x in r.get("items") or [])
    return (f'<h2>{t(r.get("title"))}</h2><p>{t(r.get("lead"))}</p></div><dl class="requirements-grid">{items}</dl>')


def render_notes(site: dict) -> str:
    return "".join(f"<p>{t(x)}</p>" for x in site.get("notes") or [])


# ------------------------------------------------------------------ build
def build() -> None:
    site = load_json(CONTENT / "site.json", {})
    insta = site.get("instagram_url") or "https://www.instagram.com/himejimatigers2025/"
    staff = staff_rows()
    news = news_rows()
    sched = schedule_rows()
    games = games_rows()
    gallery_html, gallery_files = render_gallery()

    parts = {
        "ABOUT": render_about(site),
        "POLICIES": render_policies(site),
        "STAFF_TOP": render_staff_block(site, staff, TOP_LIMIT),
        "STAFF_ALL": render_staff_block(site, staff, None),
        "STAFF_OVERLAYS": render_overlays(staff),
        "NEWS_TOP": render_news(news[:TOP_LIMIT]),
        "NEWS_ALL": render_news(news),
        "SCHEDULE_TOP": render_schedule(sched[:TOP_LIMIT], site),
        "SCHEDULE_ALL": render_schedule(sched, site),
        "GAMES_TOP": render_games(games[:TOP_LIMIT]),
        "GAMES_ALL": render_games(games),
        "GALLERY": gallery_html,
        "CONTACT": render_contact(site),
        "REQUIREMENTS": render_requirements(site),
        "NOTES": render_notes(site),
        "FOOTER_TEXT": t(site.get("footer_text")),
        "INSTAGRAM": a(insta),
    }

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for page in PAGES:
        src = (TEMPLATES / page).read_text(encoding="utf-8")
        missing = set()

        def fill(m):
            key = m[1]
            if key not in parts:
                missing.add(key)
                return m[0]
            return parts[key]

        result = re.sub(r"<!--@@([A-Z_]+)@@-->", fill, src)
        if missing:
            raise SystemExit(f"{page}: 未対応の差し込み口 {sorted(missing)}")
        (OUT / page).write_text(result, encoding="utf-8", newline="")
    for name in COPY_AS_IS:
        if (TEMPLATES / name).exists():
            shutil.copy2(TEMPLATES / name, OUT / name)
    for f in gallery_files:
        dest = OUT / f.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        data, mime = web_bytes(f)  # 大きな写真は公開用に縮小
        if mime != (mimetypes.guess_type(f.name)[0] or "image/jpeg"):
            data = f.read_bytes()  # 形式が変わる場合は拡張子と合わなくなるので元のまま
        dest.write_bytes(data)
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Built {OUT}: staff={len(staff)} news={len(news)} schedule={len(sched)} "
          f"games={len(games)} gallery={len(gallery_files)}")


if __name__ == "__main__":
    build()
