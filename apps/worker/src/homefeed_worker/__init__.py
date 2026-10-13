from homefeed_core.ytdlp_updates import activate

# Before anything imports yt-dlp, so an updated copy under DATA_DIR/ytdlp can take over.
activate()
