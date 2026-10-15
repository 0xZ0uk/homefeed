import { useState, type ComponentProps, type ReactNode } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "#/components/ui/alert-dialog";
import { Button } from "#/components/ui/button";

/**
 * A button that asks before it acts, for what can't be undone. The dialog's
 * title names what is at stake, "Cancel" leaves everything as it was and the
 * confirm button, a destructive one worded like the action, goes ahead.
 */
export function ConfirmButton({
  children,
  title,
  description,
  confirmLabel,
  onConfirm,
  disabled,
  variant = "outline",
  size = "lg",
  className,
  ...props
}: {
  /** The button's label. */
  children: ReactNode;
  /** The dialog's question, e.g. "Unsubscribe from Veritasium?". */
  title: string;
  /** What will happen, and what it leaves alone. */
  description: ReactNode;
  /** The confirm button's text; a verb, like the button's. */
  confirmLabel: string;
  onConfirm: () => void;
} & Pick<
  ComponentProps<typeof Button>,
  "disabled" | "variant" | "size" | "className" | "aria-label"
>) {
  const [open, setOpen] = useState(false);

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger
        render={
          <Button
            type="button"
            variant={variant}
            size={size}
            disabled={disabled}
            className={className}
            {...props}
          />
        }
      >
        {children}
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={() => {
              setOpen(false);
              onConfirm();
            }}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
