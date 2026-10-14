import { type ReactNode } from "react";

import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "#/components/ui/card";

/**
 * One group on the settings page: a card with a heading and description,
 * exposed as a region named by that heading. Children supply the content
 * (`CardContent`, `CardFooter`, or a form holding them).
 */
export function SettingsCard({
  id,
  title,
  description,
  children,
}: {
  /** The heading's id, which names the region. */
  id: string;
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id}>
      <Card>
        <CardHeader>
          <CardTitle render={<h3 id={id} />} className="text-lg">
            {title}
          </CardTitle>
          {description && (
            <CardDescription className="max-w-prose text-pretty">
              {description}
            </CardDescription>
          )}
        </CardHeader>
        {children}
      </Card>
    </section>
  );
}
