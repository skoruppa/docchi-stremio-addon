# Docchi Stremio Addon
![Version](https://img.shields.io/badge/version-0.1.4-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-Active-brightgreen.svg)

<div align="center">
  <img src="https://docchi.pl/static/img/logo.svg" alt="Docchi.pl Logo" width="300">
</div>

This Stremio addon allows users to access anime streams with polish subtitles available on the [Docchi.pl](http://docchi.pl/) site. 

## Supported Players

The addon supports the following video players:

- **CDA**
- **OK.ru**
- **VK.com**
- **Sibnet.ru**
- **Lycoris.cafe**
- **Dailymotion**
- **Google Drive**
- **Rumble.com**
- **Lulustream**
- **Vidtube.one**
- **UPNS**
- **MP4Upload**
- **EarnVid**
- **StreamUP**
- **Vidguard**
- **Vidnest**
- **Pixeldrain**
- **Savefiles**
- **Turbovid**
- **Buzzheavier**
- **Uqload*** 
- **Filemoon***
- **Streamtape***

**\* These players require full stream proxying through [MediaFlow Proxy](https://github.com/mhdzumair/mediaflow-proxy)** or local deployment 

## Usage 🧑‍💻

- Extension provides 3 catalogs - **Current Anime Season**, **Trending Anim**e and **Recently Added** episodes, based on the respective responses from the Docchi.api.
- Where possible I tried to implement genre filtering 

## Installation 🛠️

### Public Instance

To install the addon:

1. Visit [The Addon Website](https://stremio.docci.pl/) 
2. Copy the manifest URL.
3. Open Stremio and go to the addon search box.
4. Paste the copied manifest URL into the addon search box and press Enter. Alternatively, you can click "Open In Stremio" to automatically add the addon to Stremio.
5. In Stremio, click install, and the addon will be added and ready for use.

### Self-Hosting with Docker 🐳

**Quick Start:**
```bash
git clone --recurse-submodules https://github.com/skoruppa/docchi-stremio-addon.git
cd docchi-stremio-addon
docker-compose up -d
```

Addon will be available at `http://localhost:5000` & `http://localhost:5000/vip`

**Environment Variables:**

- `VIP_PATH` (default: `vip`) - Path for VIP features. Due to limited resources on the public server and the need to proxy certain players, some features are behind this path:
  - **IMDB ID mapping** - allows Stremio to match content using IMDB IDs
  - **Full player support** - includes Filemoon, Uqload, and Streamtape (require proxying)
  
  For self-hosting, all features should work without restrictions (and proxy - if your addon instance will be in same network as Stremio). Install the addon from the VIP path at: `http://localhost:5000/vip`

- `MAL_CLIENT_ID` - MyAnimeList Client ID (optional but recommended). The addon uses Kitsu Stremio addon for metadata, which sometimes has issues. MAL API is used as fallback.
  
  To get your Client ID:
  1. Go to [MyAnimeList API Config](https://myanimelist.net/apiconfig)
  2. Create new application (App Type: `web`)
  3. App Redirect URL and Homepage URL don't matter
  4. Copy the Client ID

- `USE_REDIS` (default: `false`) - Use Redis for anime mappings instead of TinyDB
- `REDIS_URL` - Redis connection URL (required if `USE_REDIS=true`)
- `PROXIFY_STREAMS` (default: `false`) - Enable stream proxying through [MediaFlow Proxy](https://github.com/mhdzumair/mediaflow-proxy) instance for players with IP bound streams
- `STREAM_PROXY_URL` - URL to [MediaFlow Proxy](https://github.com/mhdzumair/mediaflow-proxy) instance 
- `STREAM_PROXY_PASSWORD` - Password to [MediaFlow Proxy](https://github.com/mhdzumair/mediaflow-proxy) instance 
- `KITSU_STREMIO_API_URL` (default: `https://anime-kitsu.strem.fun`) - URL to [Stremio Kitsu Anime](https://github.com/TheBeastLT/stremio-kitsu-anime) instance.

## Support

If you encounter any issues or have any questions regarding the addon, feel free to [report them here](https://github.com/skoruppa/docchi-stremio-addon/issues).

## API References

This addon is developed using the following API references:

- **Stremio Addon SDK**: This SDK provides the necessary tools and functions to create addons for Stremio. You can refer to the [official Stremio Addon SDK documentation](https://github.com/Stremio/stremio-addon-sdk) for more information.
- **Docchi.pl**: Official API available at [devi.docchi.pl](https://dev.docchi.pl/).
- **Stremio-Kitsu-Anime**: Unofficial Kitsu anime catalog for Stremio. Credits to [TheBeastLT](https://github.com/TheBeastLT/stremio-kitsu-anime).

Please refer to these API references for detailed information on how to interact with the respective APIs.

## Acknowledgements

- **MAL-Stremio Addon**: I based a lot of this extension on a code from the [MAL-Stremio Addon](https://github.com/SageTendo/mal-stremio-addon/)


## Support 🤝

If you want to thank me for the addon, you can [buy me a coffe](https://buymeacoffee.com/skoruppa) 
