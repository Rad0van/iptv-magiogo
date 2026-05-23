<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{title}} — Magio GO VOD</title>
    <style>
        html { background:#111; color:#eee; font-family: Arial, sans-serif; }
        body { max-width: 1200px; margin: 0 auto; padding: 16px; }
        a { color:#7ab8ff; text-decoration:none; }
        a:hover { text-decoration:underline; }
        .bar { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom:16px; }
        h1 { font-size:26px; margin:0; }
        .actions a { background:#2a2a2a; padding:6px 12px; border-radius:6px; font-size:14px; }
        .grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(150px,1fr)); gap:14px; }
        .card { background:#1c1c1c; border:1px solid #2a2a2a; border-radius:8px; overflow:hidden;
                display:flex; flex-direction:column; }
        .card img { width:100%; aspect-ratio:2/3; object-fit:cover; background:#000; }
        .card.node img, .card.node .ph { aspect-ratio:16/9; }
        .ph { width:100%; aspect-ratio:2/3; background:linear-gradient(135deg,#333,#222);
              display:flex; align-items:center; justify-content:center; color:#666; font-size:34px; }
        .meta { padding:8px; }
        .meta .t { font-size:14px; font-weight:bold; line-height:1.25; }
        .meta .s { font-size:12px; color:#999; margin-top:3px; }
        .badge { font-size:11px; color:#bbb; }
        .lock { color:#e0a030; }
        .empty { color:#888; padding:30px 0; }
    </style>
</head>
<body>
    <div class="bar">
        % if back:
        <a href="{{back}}">&larr; back</a>
        % end
        <h1>{{title}}</h1>
        <span class="actions">
            % for label, href in actions:
            <a href="{{href}}">{{label}}</a>
            % end
        </span>
        <form action="/vod/browse/search" method="get" style="margin-left:auto;">
            <input type="text" name="q" placeholder="Search…" value="{{get('query','')}}"
                   style="background:#222;border:1px solid #444;color:#eee;padding:6px 10px;border-radius:6px;">
        </form>
    </div>

    % if not items:
    <div class="empty">Nothing here (you may not have a subscription for this content).</div>
    % end

    <div class="grid">
    % for it in items:
        <a class="card {{it.get('kind','')}}" href="{{it['href']}}">
            % if it.get('img'):
            <img loading="lazy" src="{{it['img']}}" alt="">
            % else:
            <div class="ph">{{it.get('icon','▶')}}</div>
            % end
            <div class="meta">
                <div class="t">{{it['title']}}</div>
                % if it.get('subtitle'):
                <div class="s">{{it['subtitle']}}</div>
                % end
                % if it.get('badge'):
                <div class="s badge {{'lock' if it.get('locked') else ''}}">{{it['badge']}}</div>
                % end
            </div>
        </a>
    % end
    </div>
</body>
</html>
