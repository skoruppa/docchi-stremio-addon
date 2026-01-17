import logging

from flask import Flask, render_template, session, url_for, redirect
from flask_compress import Compress
from app.routes.catalog import catalog_bp
from app.routes.manifest import manifest_blueprint
from app.routes.meta import meta_bp
from app.routes.stream import stream_bp
from app.routes.proxy import proxy_bp
from app.db import database
from app.utils.stream_utils import cache
from config import Config

app = Flask(__name__, template_folder='./templates', static_folder='./static')
app.config.from_object('config.Config')

# Register blueprints normally
app.register_blueprint(manifest_blueprint)
app.register_blueprint(catalog_bp)
app.register_blueprint(meta_bp)
app.register_blueprint(stream_bp)
app.register_blueprint(proxy_bp)

# Register blueprints with VIP prefix
app.register_blueprint(manifest_blueprint, name='manifest_vip', url_prefix=f'/{Config.VIP_PATH}')
app.register_blueprint(catalog_bp, name='catalog_vip', url_prefix=f'/{Config.VIP_PATH}')
app.register_blueprint(meta_bp, name='meta_vip', url_prefix=f'/{Config.VIP_PATH}')
app.register_blueprint(stream_bp, name='stream_vip', url_prefix=f'/{Config.VIP_PATH}')
app.register_blueprint(proxy_bp, name='proxy_vip', url_prefix=f'/{Config.VIP_PATH}')

Compress(app)
cache.init_app(app)

logging.basicConfig(format='%(asctime)s %(message)s')


@app.route('/')
@app.route('/configure')
def index():
    """
    Render the index page
    """
    manifest_url = f'{Config.PROTOCOL}://{Config.REDIRECT_URL}/manifest.json'
    manifest_magnet = f'stremio://{Config.REDIRECT_URL}/manifest.json'
    return render_template('index.html', logged_in=True,
                               manifest_url=manifest_url, manifest_magnet=manifest_magnet)


@app.route('/favicon.ico')
def favicon():
    """
    Render the favicon for the app
    """
    return app.send_static_file('favicon.ico')


@app.route('/callback')
def callback():
    """
    Callback URL from MyAnimeList
    :return: A webpage response with the manifest URL and Magnet URL
    """
    return redirect(url_for('index'))


if __name__ == '__main__':
    try:
        from waitress import serve

        serve(app, host='0.0.0.0', port=5000)
    finally:
        database.storage.flush()
