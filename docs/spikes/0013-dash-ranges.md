# Spike #13: DASH init and index ranges

**Question.** Where do we get `initRange` and `indexRange` for YouTube's adaptive streams so that `playback.manifest(video_id)` can generate a DASH MPD (`SegmentBase`) for Shaka Player?

**Answer.** InnerTube's player response already lists `initRange` and `indexRange` for every adaptive stream. yt-dlp receives these values and then discards them. A small hook in `gateway/ytdlp.py` copies them onto yt-dlp's format dicts, and the Gateway now returns them as `Format.init_range` and `Format.index_range`. This costs no extra requests and added no measurable latency. The hook worked for 100% of the adaptive formats tested: 6 videos and 271 formats across avc1, vp9, av01, AAC and Opus, including 24-language dubbed audio.

For the rare case where a format arrives without ranges (for example, after a yt-dlp update renames the private method we hook), #14 should fall back to probing the first 2 KB of the stream and parsing the `sidx` box (mp4) or the `Cues` element (webm). The probe agreed byte-for-byte with InnerTube on all 86 formats tested, with a median of 75 ms per stream. ffmpeg remuxing to fragmented MP4 is not recommended.

---

## Setup

- yt-dlp 2026.08.19 (the version pinned in `packages/core`). With the default clients `visionos` and `web`, both clients return `streamingData.adaptiveFormats`.
- The test videos, picked to cover different cases:

| Video                         | Length   | Why                                             |
| ----------------------------- | -------- | ----------------------------------------------- |
| `jNQXAC9IVRw` "Me at the zoo" | 19 s     | Old upload; DRC and regular files share an itag |
| `NiCgcUTL9_Q`                 | 34.5 min | Long; 4K vp9/av01                               |
| `j9p3Sn8ROL4`                 | 70 s     | A Short; includes itags 779/780/787/788         |
| `dQw4w9WgXcQ`                 | 3.5 min  | Popular; JS-challenge path                      |
| `aqz-KE-bpKQ` Big Buck Bunny  | 10 min   | 60 fps, 4K                                      |
| `0e3GPea1Tyg`                 | 25 min   | 24 dubbed audio languages (138 formats)         |

- Network use was light: one extraction per video, one 1–4 KB range request per probed format, and a few ffmpeg runs.
- The throwaway scripts used here are not committed. The parser is included in the appendix.

## Option (a): ranges in the InnerTube player response

To see the raw player responses, I wrapped yt-dlp's `YoutubeIE._extract_formats_and_subtitles(video_id, player_responses, ...)` and printed `streamingData.adaptiveFormats`. A typical entry:

```json
{
  "itag": 140,
  "mimeType": "audio/mp4; codecs=\"mp4a.40.2\"",
  "initRange": { "start": "0", "end": "722" },
  "indexRange": { "start": "723", "end": "778" },
  "contentLength": "309288",
  "lastModified": "1767107011597808"
}
```

What the responses showed:

- **Every** adaptive format from both clients had both ranges. That was 16, 32 and 28 formats for the first three videos; the per-client counts were `[(16,16), (14,14)]`, `[(32,32), (34,34)]` and `[(28,28), (30,30)]`.
- **The itag does not identify a stream on its own.** For "Me at the zoo", itag 140 appears twice: the regular file has init `0-722`, and the DRC file has init `0-631`. On the dubbed video, itag 251 appears 24 times, once per language. Each googlevideo URL carries `lmt=<lastModified>` and `clen=<contentLength>`. Matching on `(itag, lmt)` was exact in every case.
- The layout is always "header, then index": `init = 0..N` and `index = N+1..M`. In mp4 the header is `ftyp`+`moov` and the index is `sidx`. In webm the header is EBML through `Tracks` and the index is `Cues`, which YouTube writes before the first `Cluster`.
- The index size grows with duration. It was about 50 bytes for 19 s, 0.9 KB for 70 s, 3.2–6.3 KB for 34 min, and 5.4 KB for 25 min of vp9 1080p. So for a 10-hour video, expect roughly 100 KB.
- There is no `dashManifestUrl` for VOD in either client. YouTube stopped serving DASH manifests long ago, so we have to generate our own.
- `expiresInSeconds` is `21540` (about 6 h) for both clients. This matches the `expire=` value in the URLs.

## Option (b): yt-dlp internals

yt-dlp does not expose the ranges. There is no reference to `initRange` or `indexRange` anywhere in its source:

```
$ grep -rn -i 'initRange\|indexRange\|init_range\|index_range' .venv/lib/python3.13/site-packages/yt_dlp
(no output)
```

`process_format_stream` in `yt_dlp/extractor/youtube/_video.py` builds each format dict from a fixed set of keys: `contentLength`, `bitrate`, `mimeType` and so on. The ranges are not among them. The info dict and our recorded fixtures had no range fields either. However, yt-dlp passes the full `player_responses` list into `_extract_formats_and_subtitles`, which is a generator that yields one format dict at a time and then the subtitles.

That is where the hook goes. It is implemented in `gateway/ytdlp.py`:

```python
class _DashRangesYoutubeIE(YoutubeIE):
    @classmethod
    def ie_key(cls) -> str:
        return YoutubeIE.ie_key()  # replaces the stock "Youtube" extractor in this YoutubeDL

    def _extract_formats_and_subtitles(self, video_id, player_responses, *args, **kwargs):
        ranges = dash_ranges(player_responses)          # {(itag, "lmt"|"clen", value): ranges}
        for item in super()._extract_formats_and_subtitles(video_id, player_responses, *args, **kwargs):
            if ranges and isinstance(item, dict) and "format_id" in item:
                add_dash_ranges(item, ranges)           # matched via the URL's lmt=, then clen=
            yield item
```

The subclass is registered per `YoutubeDL` instance with `ydl.add_info_extractor(_DashRangesYoutubeIE())`, so nothing global is patched. Live results through the real Gateway:

```
jNQXAC9IVRw 1.08s 16/16 https formats have ranges   139-drc 0-640 641-696 | 139 0-731 732-787
NiCgcUTL9_Q 1.00s 32/32 https formats have ranges
dQw4w9WgXcQ 1.55s 27/27 with ranges  (mp4a 2, opus 3, avc1 6, vp9 8, av01 8)
aqz-KE-bpKQ 1.07s 32/32 with ranges  (mp4a 4, opus 6, avc1 6, vp9 8, av01 8)
0e3GPea1Tyg 1.74s 138/138 with ranges, 24 audio languages
```

Extraction time is the same as before, about 1–1.7 s, because no new requests are made. HLS (`m3u8_native`) formats correctly get no ranges.

**Risks.**

- `_extract_formats_and_subtitles` is a private method. A yt-dlp upgrade could rename it, which means silently no ranges, or change its signature.
  - Mitigation: the hook catches its own errors and never breaks extraction.
  - Mitigation: a canary test asserts that the method still exists and that its first parameters are `(self, video_id, player_responses)`.
  - Mitigation: #14 should treat missing ranges as "probe instead" (option c), not as an error.
- Matching relies on `lmt`/`clen` in the URL. A `clen` that maps to two different range sets is dropped rather than guessed.

The alternative of calling InnerTube ourselves would duplicate yt-dlp's client selection, PO-token handling and signature/n solving. That is exactly what the Gateway exists to avoid, so I rejected it.

## Option (c): probe the `sidx` box or WebM Cues

This option reads a few KB from the start of each stream and parses top-level mp4 boxes or EBML elements. Only the **header** of the index box is needed, because the header gives its size. So 1 KB is enough even when the index itself is 6 KB.

The actual container layout, from a 1 KB read of each stream:

```
137   mp4  ftyp@0+28  moov@28+713  sidx@741+3488                        -> init 0-740, index 741-4228
248   webm EBML@0+36 Segment@36 SeekHead@45+47 Info@92+59 Tracks@151+70 Cues@221+5160
                                                                       -> init 0-220, index 221-5380
140-5 m4a  ftyp@0+24  moov@24+699  sidx@723+1892
251-3 webm EBML@0+36 Segment@36 SeekHead@48+68 Info@116+59 Tracks@175+84 Cues@259+2680
```

I compared the probe results against InnerTube's values, which I treated as the ground truth:

```
139-drc  m4a  mp4a.40.5      HTTP 206  1024B    344ms init=(0, 731) index=(732, 3259) MATCH
278      webm vp9            HTTP 206  1024B    153ms init=(0, 218) index=(219, 6329) MATCH
137      mp4  avc1.640028    HTTP 206  1024B     76ms init=(0, 740) index=(741, 4996) MATCH
313      webm vp9            HTTP 206  1024B     17ms init=(0, 220) index=(221, 6542) MATCH
401      mp4  av01.0.12M.08  HTTP 206  1024B     99ms init=(0, 700) index=(701, 4956) MATCH
251-15   webm opus           HTTP 206  2048B    204ms init=(0, 258) index=(259, 2940) MATCH
...
```

- **Reliability:** 86 of 86 formats matched exactly, across 4 videos. The set covered avc1, vp9, av01, mp4a.40.2, mp4a.40.5, Opus, DRC files and dubbed tracks.
- **Latency per format:** median 75 ms, p90 325 ms, p95 350 ms, max 577 ms. That is one round trip, and parsing takes about 0.01–0.03 ms.
- **Cost:** a manifest with all ~30 formats would need ~30 requests. Run sequentially, that is about 2–3 s on a cold start; run in parallel, about 0.3–0.6 s. With option (b) the cost is zero.
- **Weaknesses:**
  - It needs a working media URL. An expired URL or a 403 caused by an unsolved n/PO-token challenge breaks it.
  - It assumes the index comes before the media. That held for every YouTube file tested. The parser returns "not found" if a `Cluster` or `moof` appears first, and the fallback for that case would be the WebM `SeekHead`.

## Option (d): ffmpeg remux to fragmented MP4

This option streams through `ffmpeg -c copy -f mp4 -movflags frag_keyframe+empty_moov` from googlevideo URLs, with seeking done via `-ss`:

```
avc1 1080p + m4a  ss=0    t=10: first byte 3921 ms, done 5957 ms, 1.65 MB
avc1 1080p + m4a  ss=1200 t=10: first byte 4625 ms, done 6659 ms, 1.74 MB
vp9 1080p webm->fmp4 ss=600 t=10: first byte  543 ms, done 6409 ms, 1.48 MB
m4a, whole 34-min file:          first byte 402 s (!), 13 MB after ~7 min, then killed
```

The last result is not an ffmpeg problem. **googlevideo throttles un-ranged GETs:**

```
ranged 10MB chunk:     HTTP 206 10485760B in 0.40s (TTFB 0.087s)
unranged GET (8s cap): HTTP 200   262144B in 8.00s   <- 256 KB, then stalls
ranged 64KB mid-file:  HTTP 206    65536B in 0.35s
```

Remuxing gives 4–5 s to first byte, needs a new ffmpeg process for every seek, and uses CPU and memory per viewer. It gives no ABR, because there is one rendition per process, and it fights the throttling unless we split the input into chunks ourselves. It is clearly worse than serving YouTube's files as they are with SegmentBase. Keep it only as a last resort for a future source that has no index, such as a progressive-only format.

## Comparison

|                             | (a)+(b) InnerTube ranges via the yt-dlp hook                | (c) Probe sidx/Cues                                             | (d) ffmpeg remux                                 |
| --------------------------- | ----------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------ |
| Extra requests per manifest | **0**                                                       | 1 per format (~30)                                              | Continuous upstream stream                       |
| Added latency               | **~0** (extraction ~1–1.7 s is unchanged)                   | median 75 ms per format; ~0.3–0.6 s for all formats in parallel | 0.5–4.6 s to first byte, and again on every seek |
| Correctness                 | Source of truth                                             | 86/86 matched                                                   | n/a (we create the index)                        |
| Codecs                      | avc1, vp9, av01, AAC, Opus, DRC, dubbed                     | Same                                                            | Any, but webm is copied into mp4                 |
| Breaks when                 | yt-dlp renames a private method (fails soft to "no ranges") | URL is expired or blocked; a container is laid out unusually    | Throttling, CPU load, seek latency               |
| Server cost                 | None                                                        | Small                                                           | ffmpeg per viewer                                |
| ABR / seeking in Shaka      | Native (SegmentBase + sidx/Cues)                            | Native                                                          | Poor                                             |

## URL expiry

- **Ranges belong to the file, not the URL.** Two extractions minutes apart produced different URLs but the same `lmt`, `clen` and ranges (for example, 139-drc was `0-640/641-696` both times). So ranges can be cached by `(video_id, format_id, lmt)` for as long as we like, and only the URL needs refreshing.
- URLs expire about 6 h after extraction (`expiresInSeconds: 21540`), and `Format.expires_at` already parses this. The MPD should **never** contain googlevideo URLs. `BaseURL` should point at our proxy, `GET /videos/{id}/media/{format_id}`. That way the manifest stays valid when the URL expires, and the proxy re-resolves the URL through `Gateway.get_formats` when `expires_at` is close or upstream returns 403. The ranges stay valid as long as `lmt` is unchanged.
- If `lmt` changes after a refresh (YouTube re-encoded the file), the ranges in an open manifest are stale. The proxy should compare `lmt` and `clen` and return an error (or have the player reload the manifest) rather than serve mismatched bytes. In these tests no file changed `lmt` between extractions.

## Recommendation for #14

1. **Build the manifest from `Format.init_range` and `Format.index_range`.** Gateway support is implemented in this spike. Write one `Representation` per adaptive `https` format, using `SegmentBase`:

   ```xml
   <AdaptationSet mimeType="video/mp4" contentType="video" subsegmentAlignment="true">
     <!-- NiCgcUTL9_Q itag 137, values straight from Format (recorded fixture) -->
     <Representation id="137" codecs="avc1.640028" bandwidth="1713054" width="1920" height="1080" frameRate="24">
       <BaseURL>/api/videos/NiCgcUTL9_Q/media/137</BaseURL>
       <SegmentBase indexRange="741-4996"><Initialization range="0-740"/></SegmentBase>
     </Representation>
   </AdaptationSet>
   ```

   `str(ByteRange)` already returns the `"start-end"` form these attributes need. Use `Video.duration_seconds` for `mediaPresentationDuration`; Shaka reads exact segment times from `sidx`/`Cues`. Group the representations into AdaptationSets by mime type. Audio needs a further split: put DRC (`Format.is_drc`) and each `language` in separate AdaptationSets, or drop DRC.

2. **Fall back to probing** (option c) for any adaptive format whose ranges are `None`.
   - Request `Range: bytes=0-2047` through the same upstream path the proxy uses.
   - Parse it with the appendix parser.
   - If the index header is not within the first 2 KB, refetch using the size taken from the box header.
   - Cache the result by `(video_id, format_id, lmt)`.
   - If the probe also fails, leave the format out of the manifest. Do not fail the whole manifest.

3. **The range proxy must always send ranged requests upstream** and cap each one at 10 MB or less. yt-dlp uses the same 10 MB chunk size. Un-ranged GETs get throttled to a trickle, as the measurements above show. Shaka with SegmentBase sends ranged requests per subsegment, which fits this well.

4. **Do not use ffmpeg remuxing** for the player.

5. **Codec choice belongs to the client.** List mp4 (avc1/av01 + AAC) and webm (vp9 + Opus) as separate AdaptationSets, and let Shaka pick what MSE supports. Safari/iOS cannot play WebM through MSE, so make sure mp4 is always present.

## Side finding (out of scope)

For `dQw4w9WgXcQ` and `0e3GPea1Tyg`, yt-dlp warned: `n challenge solving failed ... Remote components challenge solver script (deno) ... were skipped`. Ranges were unaffected. However, URLs with an unsolved n parameter can be throttled or return 403, which would affect the proxy and probing. The Gateway should probably enable yt-dlp's EJS remote components (`deno` is installed). This needs a separate ticket.

## What changed in code (behind the Gateway)

- `gateway/models.py`: new `ByteRange(start, end)` (inclusive; `str()` gives `"start-end"`). `Format` gains `init_range: ByteRange | None` and `index_range: ByteRange | None`. Both default to `None`, so `FakeGateway`/`make_format` and existing callers are unaffected.
- `gateway/normalize.py`: two new pure helpers. `dash_ranges(player_responses)` indexes the raw ranges by `(itag, lmt|clen)` and drops ambiguous keys. `add_dash_ranges(fmt, ranges)` matches a yt-dlp format dict through its URL. `_format` reads `init_range`/`index_range` into `ByteRange`.
- `gateway/ytdlp.py`: `_DashRangesYoutubeIE` is the hook described above, registered per `YoutubeDL`. yt-dlp is still imported only here.
- Fixtures: the three `video_*.json` fixtures were re-recorded, so they now include `init_range`/`index_range`.
- Tests: `tests/test_gateway_dash_ranges.py` adds 10 tests, with no network access:
  - recorded ranges for mp4 and webm;
  - "every adaptive stream has ranges, HLS has none";
  - lmt matching, clen fallback, ambiguity and malformed input;
  - the hook wrapping a stubbed yt-dlp method;
  - `extract_info` installing the hook;
  - a canary on the private method's signature.

<details>
<summary>Appendix: probe parser used in the spike (basis for the #14 fallback)</summary>

```python
import struct

def mp4_ranges(buf: bytes):
    """ftyp/moov/sidx: init = 0..end of moov, index = the sidx box."""
    pos, init_end = 0, None
    while pos + 8 <= len(buf):
        size, typ = struct.unpack(">I4s", buf[pos:pos + 8])
        if size == 1:
            size = struct.unpack(">Q", buf[pos + 8:pos + 16])[0]
        if typ == b"moov":
            init_end = pos + size - 1
        elif typ == b"sidx":
            return (0, init_end), (pos, pos + size - 1)
        elif typ in (b"moof", b"mdat"):
            break
        pos += size
    return None

def ebml_vint(buf, pos, keep_marker):
    first, length = buf[pos], 1
    while length <= 8 and not first & (0x80 >> (length - 1)):
        length += 1
    value = first if keep_marker else first & (0xFF >> length)
    for b in buf[pos + 1:pos + length]:
        value = (value << 8) | b
    return value, length

def webm_ranges(buf: bytes):
    """EBML, Segment{SeekHead, Info, Tracks, Cues, Cluster...}: init = 0..before Cues, index = Cues."""
    pos = 0
    _, n = ebml_vint(buf, pos, True); pos += n
    size, n = ebml_vint(buf, pos, False); pos += n + size        # skip the EBML header
    eid, n = ebml_vint(buf, pos, True); pos += n
    assert eid == 0x18538067                                     # Segment
    _, n = ebml_vint(buf, pos, False); pos += n
    while pos < len(buf):
        start = pos
        eid, n = ebml_vint(buf, pos, True); pos += n
        size, n = ebml_vint(buf, pos, False); pos += n
        if eid == 0x1C53BB6B:                                    # Cues
            return (0, start - 1), (start, pos + size - 1)
        if eid == 0x1F43B675:                                    # Cluster before Cues
            return None
        pos += size
    return None
```

</details>
