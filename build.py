from pathlib import Path
import json,html
ROOT=Path(__file__).resolve().parent
C=ROOT/'content'
def esc(s): return html.escape(str(s or ''),quote=True)
def items(name):
    found=[]
    for f in (C/name).glob('*.json'):
        try:
            x=json.loads(f.read_text(encoding='utf8'))
            if x.get('published') is True: found.append(x)
        except (ValueError,OSError): continue
    return sorted(found,key=lambda x:str(x.get('date','')),reverse=True)
s=json.loads((C/'settings.json').read_text(encoding='utf8'))
news=items('news');games=items('games');schedule=items('schedule');gallery=items('gallery')
def cards(rows,kind):
    if not rows:return '<p class="empty">現在、公開中の情報はありません。最新情報はInstagramをご覧ください。</p>'
    out=[]
    for x in rows[:12]:
        body=esc(x.get('body','')).replace('\\n','<br>')
        extra=('<strong>対戦相手：</strong>'+esc(x.get('opponent',''))+'　<strong>スコア：</strong>'+esc(x.get('score',''))) if kind=='games' else ('<strong>場所：</strong>'+esc(x.get('location','')) if kind=='schedule' else '')
        out.append('<article class="content-card"><time class="muted">'+esc(x.get('date',''))+'</time><h3>'+esc(x.get('title',''))+'</h3><p>'+extra+'</p><p>'+body+'</p></article>')
    return ''.join(out)
photos=[]
for x in gallery[:12]:
    path=str(x.get('image',''))
    if not path.startswith('/media/') or any(t in path for t in ('..','\\','"','<','>')): continue
    photos.append('<figure style="margin:0"><img class="photo" loading="lazy" src="'+esc(path)+'" alt="'+esc(x.get('alt') or x.get('title'))+'"><figcaption class="muted">'+esc(x.get('title'))+'</figcaption></figure>')
if not photos: photos=['<p class="empty">写真は準備中です。掲載許可を確認した写真から公開します。</p>']
page=(ROOT/'template.html').read_text(encoding='utf8')
for key,value in dict(headline=s.get('headline',''),growth_title=s.get('growth_title',''),growth_body=s.get('growth_body',''),description=s.get('description',''),recruitment=s.get('recruitment',''),recruitment_title=s.get('recruitment_title',''),recruitment_body=s.get('recruitment_body',''),recruitment_note=s.get('recruitment_note',''),location=s.get('location',''),schedule_note=s.get('schedule_note',''),fee_note=s.get('fee_note',''),equipment=s.get('equipment',''),rental=s.get('rental',''),trial_fee=s.get('trial_fee',''),instagram=s.get('instagram',''),news=cards(news,'news'),games=cards(games,'games'),schedule=cards(schedule,'schedule'),gallery=''.join(photos)).items():
    page=page.replace('{{'+key+'}}',value.replace('src="/media/','src="media/') if key in ('news','games','schedule','gallery') else esc(value))
(ROOT/'index.html').write_text(page,encoding='utf8')
print('Generated index.html')
