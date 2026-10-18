"""Preview the real playlist callbacks locally, with disposable demo data.

Run: python3 tools/preview_playlist.py
Requires discord.py==2.7.1. No bot token, Discord connection, or media requests.
"""

import argparse
import asyncio
import json
import logging
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Rei'))
try:
    import discord
    from playlist_ui import PlaylistEditor
    from playlist_links import normalize_song_url
    from playlists import PlaylistError, PlaylistSong, PlaylistStore
except ModuleNotFoundError as error:
    raise SystemExit("Install the preview dependency first: python3 -m pip install 'discord.py==2.7.1'") from error


class PreviewResponse:
    def __init__(self, app):
        self.app = app
        self.done = False

    def is_done(self):
        return self.done

    async def defer(self, **kwargs):
        self.done = True

    async def edit_message(self, **kwargs):
        self.done = True
        await self.app.message.edit(**kwargs)

    async def send_message(self, content=None, **kwargs):
        self.done = True
        self.app.notice = content or ''

    async def send_modal(self, modal):
        self.done = True
        self.app.modal = modal


class PreviewMessage:
    def __init__(self):
        self.embed = None
        self.view = None
        self.content = None

    async def edit(self, **kwargs):
        for name in ('embed', 'view', 'content'):
            if name in kwargs:
                setattr(self, name, kwargs[name])
        return self


class PreviewApp:
    def __init__(self, root):
        self.store = PlaylistStore(root)
        self.modal = None
        self.notice = ''
        self.message = PreviewMessage()
        self.editor = None
        titles = [
            'Happy Lucky Chappy', 'アイドル / Idol', '夜に駆ける / Yoru ni Kakeru', '群青 / Gunjo',
            '怪物 / Monster', '踊り子 / Odoriko', '花になって / Be a flower', '青のすみか / Where Our Blue Is',
            'SPECIALZ', 'Bling-Bang-Bang-Born', '晩餐歌 / Bansanka', 'Pretender', 'ミックスナッツ / Mixed Nuts',
            'Subtitle', 'ドライフラワー / Dried Flower', '水平線 / Suiheisen', '新時代 / New Genesis',
            '唱 / Show', '逆光 / Backlight', 'KICK BACK', 'チェンソーブラッド / CHAINSAW BLOOD',
            '残響散歌 / Zankyosanka', '紅蓮華 / Gurenge',
        ]
        songs = [PlaylistSong(title, str(i), f'https://example.invalid/song/{i}') for i, title in enumerate(titles)]
        self.store.append(1, 'Favorites', songs, create=True)
        self.store.append(1, 'Chill', songs[:4], create=True)
        self.store.create(1, 'Empty')

    @staticmethod
    def extract_song(link):
        parsed = urlsplit(normalize_song_url(link))
        query = parse_qs(parsed.query)
        title = query.get('title', [None])[0] or query.get('v', [None])[0] or parsed.path.rstrip('/').split('/')[-1]
        return PlaylistSong(f'Demo: {title or parsed.netloc}', str(title), parsed.geturl())

    async def open(self, name=None):
        if self.editor is not None:
            self.editor.stop()
        self.modal = None
        self.notice = ''
        self.editor = PlaylistEditor(self.store, 1, 1, self.extract_song, name=name)
        self.editor.message = self.message
        await self.message.edit(embed=self.editor.render(), view=self.editor, content=None)
        return self.state()

    def interaction(self):
        async def original_response():
            return self.message

        return SimpleNamespace(guild_id=1, user=SimpleNamespace(id=1),
                               response=PreviewResponse(self), original_response=original_response,
                               edit_original_response=self.message.edit)

    def state(self):
        return dict(embed=self.message.embed.to_dict() if self.message.embed else None,
                    components=self.message.view.to_components() if self.message.view else [],
                    content=self.message.content,
                    modal=self.modal.to_dict() if self.modal else None,
                    notice=self.notice)

    async def dispatch(self, payload):
        self.notice = ''
        action = payload.get('action')
        if action == 'open':
            return await self.open()
        if action == 'cancel_modal':
            self.modal = None
            return self.state()
        if action == 'state':
            return self.state()
        event = self.interaction()
        if action == 'submit_modal':
            modal, self.modal = self.modal, None
            if modal is None:
                raise ValueError('This form has already closed.')
            for item in modal.walk_children():
                if isinstance(item, discord.ui.TextInput):
                    value = payload.get('values', {}).get(item.custom_id, '')
                    if not isinstance(value, str) or (item.required and not value.strip()):
                        raise ValueError('Complete the required field.')
                    if item.max_length is not None and len(value) > item.max_length:
                        raise ValueError('The field is too long.')
                    item._refresh_state(event, {'value': value})
            if await modal.interaction_check(event):
                try:
                    await modal.on_submit(event)
                except Exception as error:
                    await modal.on_error(event, error)
            modal.stop()
        elif action == 'component':
            item = next((item for item in self.editor.children
                         if item.custom_id == payload.get('id')), None)
            if item is None:
                raise ValueError('This control changed. Refresh the preview.')
            if item.disabled:
                return self.state()
            if await self.editor.interaction_check(event):
                if isinstance(item, discord.ui.Select):
                    values = payload.get('values', [])
                    allowed = {option.value for option in item.options}
                    if not isinstance(values, list) or not all(value in allowed for value in values):
                        raise ValueError('Choose a valid option.')
                    if not item.min_values <= len(values) <= item.max_values:
                        raise ValueError('Choose the right number of options.')
                    item._refresh_state(event, {'values': values})
                try:
                    await item.callback(event)
                except Exception as error:
                    await self.editor.on_error(event, error, item)
        else:
            raise ValueError('Unknown preview action.')
        return self.state()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory(prefix='reibot-preview-') as folder:
        async def create_app():
            app = PreviewApp(Path(folder))
            await app.open('Favorites')
            return app

        app = asyncio.run_coroutine_threadsafe(create_app(), loop).result()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, content, content_type='application/json; charset=utf-8'):
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))

            def do_GET(self):
                if self.path == '/':
                    self.reply(200, Path(__file__).with_suffix('.html').read_text(), 'text/html; charset=utf-8')
                elif self.path == '/state':
                    state = asyncio.run_coroutine_threadsafe(app.dispatch({'action': 'state'}), loop).result(timeout=10)
                    self.reply(200, json.dumps(state))
                else:
                    self.reply(404, '{}')

            def do_POST(self):
                if self.path != '/interact':
                    self.reply(404, '{}')
                    return
                origin = self.headers.get('Origin')
                if origin and origin != f'http://127.0.0.1:{args.port}':
                    self.reply(403, json.dumps({'error': 'Use the local preview address.'}))
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 16384:
                        raise ValueError('Invalid request size.')
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError('Invalid preview request.')
                    state = asyncio.run_coroutine_threadsafe(app.dispatch(payload), loop).result(timeout=60)
                    self.reply(200, json.dumps(state))
                except (ValueError, TypeError, KeyError) as error:
                    self.reply(400, json.dumps({'error': str(error)}))
                except Exception:
                    logging.exception('Preview request failed')
                    self.reply(500, json.dumps({'error': 'The preview could not complete this action.'}))

        try:
            with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
                print(f'Playlist preview: http://127.0.0.1:{args.port}', flush=True)
                print('Disposable demo playlists. No Discord token or media access. Ctrl+C to stop.', flush=True)
                server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            app.editor.stop()
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.close()


if __name__ == '__main__':
    main()
