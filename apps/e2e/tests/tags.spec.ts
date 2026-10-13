import { WOODWORKING, apiGet, expect, open, test } from "./fixtures";

const video = WOODWORKING.videos[1];

test("add and remove tags by hand, with the keyboard", async ({
  page,
  request,
}) => {
  await open(page, `/watch/${video.id}`);
  const tags = page.getByRole("list", { name: "Tags" }).getByRole("listitem");
  await expect(tags).toHaveText(["workbench", "woodworking", "hand tools"]);

  // Type a new tag and press Enter: the typed text is the first option.
  const add = page.getByRole("combobox", { name: "Add tag" });
  await add.fill("Dovetail Joints");
  await expect(
    page.getByRole("option", { name: "Add “Dovetail Joints”" }),
  ).toBeVisible();
  await add.press("Enter");
  await expect(tags).toHaveText([
    "Dovetail Joints",
    "workbench",
    "woodworking",
    "hand tools",
  ]);
  await expect(add).toHaveValue("");

  // Tags already on the video aren't suggested again.
  await add.fill("hand");
  await expect(page.getByRole("option", { name: /Add “hand”/ })).toBeVisible();
  await expect(page.getByRole("option", { name: /hand tools/ })).toHaveCount(0);
  await add.press("Escape");
  await add.fill("");

  // Remove a tag from its chip, by keyboard.
  const remove = page.getByRole("button", { name: "Remove tag workbench" });
  await remove.focus();
  await remove.press("Enter");
  await expect(tags).toHaveText([
    "Dovetail Joints",
    "woodworking",
    "hand tools",
  ]);
  await expect(add).toBeFocused();

  const saved = await apiGet<{ tags: { slug: string; source: string }[] }>(
    request,
    `/videos/${video.id}`,
  );
  expect(saved.body.tags.map((tag) => [tag.slug, tag.source])).toEqual([
    ["dovetail-joints", "manual"],
    ["woodworking", "llm"],
    ["hand-tools", "llm"],
  ]);
});
