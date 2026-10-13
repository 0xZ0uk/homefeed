import { EXPORT_PATH } from "#/lib/export";

/** Download everything as one JSON file (see `routes/export[.]json.ts`). */
export function DataExport() {
  return (
    <section aria-labelledby="export-heading" className="flex flex-col gap-3">
      <h3 id="export-heading" className="text-lg font-semibold">
        Export your data
      </h3>
      <p className="text-gray-600">
        Download your ratings, channels and curation, feed history, watch
        history, queue, playlists and settings as one JSON file. Cached data
        such as embeddings and tags isn't included, and neither are API keys.
      </p>
      <div>
        <a
          href={EXPORT_PATH}
          download
          className="inline-block rounded bg-black px-3 py-2 font-medium text-white"
        >
          Download JSON
        </a>
      </div>
    </section>
  );
}
