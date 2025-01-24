# docchi-stremio-addon

This Stremio addon allows users to access anime streams with polish subtitles available on the [Docchi.pl](http://docchi.pl) site. 

## Supported Players
As the stream data needs to be extracted from web players, not all available players at dochi.pl are supported
- **Uqload**: on remote environments through the [MediaFlow Proxy](https://github.com/mhdzumair/mediaflow-proxy/issues). Locally deployed does need a proxy
- **CDA**
- **OK.ru**
- **VK.com**
- **Sibnet.ru**
- **Lycoris.cafe**
- **Dailymotion**
- **Google Drive**

## Usage 🧑‍💻

- Extension provides 3 catalogs - **Current Anime Season**, **Trending Anim**e and **Recently Added** episodes, based on the respective responses from the Docchi.api.
- Where possible I tried to implement genre filtering 

## Installation 🛠️

To install the addon:

1. Visit [The Addon Website](https://stremio.docci.pl/) 
2. Copy the manifest URL.
4. Open Stremio and go to the addon search box.
5. Paste the copied manifest URL into the addon search box and press Enter. Alternatively, you can click "Open In Stremio" to automatically add the addon to Stremio.
6. In Stremio, click install, and the addon will be added and ready for use.

## Support

If you encounter any issues or have any questions regarding the addon, feel free to [report them here](https://github.com/skoruppa/docchi-stremio-addon/issues).

## API References

This addon is developed using the following API references:

- **Stremio Addon SDK**: This SDK provides the necessary tools and functions to create addons for Stremio. You can refer to the [official Stremio Addon SDK documentation](https://github.com/Stremio/stremio-addon-sdk) for more information.
- **Docchi.pl**: Official API available at [devi.docchi.pl](https://dev.docchi.pl/).
- **Stremio-Kitsu-Anime**: Unofficial Kitsu anime catalog for Stremio. Credits to [TheBeastLT](https://github.com/TheBeastLT/stremio-kitsu-anime).

Please refer to these API references for detailed information on how to interact with the respective APIs.

## Acknowledgements

- **MAL-Stremio Addon**: I based a lot of this extension on a code from the [MAL-Stremio Addon](https://github.com/SageTendo/mal-stremio-addo)