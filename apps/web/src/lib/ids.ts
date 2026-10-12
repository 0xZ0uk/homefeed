/** YouTube ids as they appear in our URLs. */

const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
/** A stream's format id from the manifest, e.g. "137", "140-drc", "251-1". */
const FORMAT_ID = /^[A-Za-z0-9_-]{1,40}$/;

export function isVideoId(value: string): boolean {
  return VIDEO_ID.test(value);
}

export function isFormatId(value: string): boolean {
  return FORMAT_ID.test(value);
}
