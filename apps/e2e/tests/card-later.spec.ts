import { WOODWORKING, apiGet, expect, feedItem, open, test } from "./fixtures";
import { actionStatus, cardButton } from "./cards";

const video = WOODWORKING.videos[0];

test("Later puts the video in the queue, and Undo takes it out again", async ({
  page,
  request,
}) => {
  const queued = async () =>
    (await apiGet<{ video_id: string }[]>(request, "/queue")).body.map(
      (item) => item.video_id,
    );
  await open(page, "/");
  const later = cardButton(feedItem(page, video.title), "Later");
  // It can be pressed once the queue has loaded (a press before is ignored).
  const settled = () =>
    expect(later).not.toHaveAttribute("aria-disabled", "true");
  await settled();
  await expect(later).toHaveAttribute("aria-pressed", "false");

  await later.click();
  await expect(
    actionStatus(page, `Added “${video.title}” to your queue.`),
  ).toBeVisible();
  await expect(later).toHaveAttribute("aria-pressed", "true");
  await expect.poll(queued).toEqual([video.id]);

  await actionStatus(page, "Added")
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(actionStatus(page, "Undone.")).toBeVisible();
  await expect(later).toHaveAttribute("aria-pressed", "false");
  await expect.poll(queued).toEqual([]);
});

test("Later, pressed again, takes the video out of the queue, with an Undo", async ({
  page,
  request,
}) => {
  const queued = async () =>
    (await apiGet<{ video_id: string }[]>(request, "/queue")).body.map(
      (item) => item.video_id,
    );
  await open(page, "/");
  const later = cardButton(feedItem(page, video.title), "Later");
  await expect(later).not.toHaveAttribute("aria-disabled", "true");
  await later.click();
  await expect(later).toHaveAttribute("aria-pressed", "true");
  await expect(later).not.toHaveAttribute("aria-disabled", "true");

  await later.click();

  await expect(
    actionStatus(page, `Removed “${video.title}” from your queue.`),
  ).toBeVisible();
  await expect(later).toHaveAttribute("aria-pressed", "false");
  await expect.poll(queued).toEqual([]);

  await expect(later).not.toHaveAttribute("aria-disabled", "true");
  await actionStatus(page, "Removed")
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(later).toHaveAttribute("aria-pressed", "true");
  await expect.poll(queued).toEqual([video.id]);
});
