/** Chapters of a video, as `GET /videos/{id}` lists them. */

export interface Chapter {
  title: string;
  start_seconds: number;
  end_seconds: number;
}

/** Index of the chapter playing at `time`, or -1 before the first one. */
export function chapterIndexAt(
  chapters: readonly Chapter[],
  time: number,
): number {
  let index = -1;
  chapters.forEach((chapter, i) => {
    if (chapter.start_seconds <= time) index = i;
  });
  return index;
}
