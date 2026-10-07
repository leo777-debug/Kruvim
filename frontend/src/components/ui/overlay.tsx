import * as RDialog from "@radix-ui/react-dialog";
import * as RMenu from "@radix-ui/react-dropdown-menu";
import * as RSelect from "@radix-ui/react-select";
import { Check, ChevronDown, X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { useFieldLabel } from "./primitives";

export function Dialog({ open, onOpenChange, title, description, children, footer, wide }: {
  open: boolean; onOpenChange: (v: boolean) => void; title: ReactNode; description?: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-40 bg-[#0b1220]/40 animate-fade-in" />
        <RDialog.Content className={cn("fixed left-1/2 top-1/2 z-50 w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-line bg-panel shadow-pop animate-fade-in",
          wide ? "max-w-3xl" : "max-w-lg")}>
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div>
              <RDialog.Title className="text-[15px] font-semibold">{title}</RDialog.Title>
              {description && <RDialog.Description className="mt-1 text-[13px] text-muted">{description}</RDialog.Description>}
            </div>
            <RDialog.Close className="rounded p-1 text-muted hover:bg-raised hover:text-fg"><X className="h-4 w-4" /></RDialog.Close>
          </div>
          <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-line bg-raised/50 px-5 py-3 rounded-b-lg">{footer}</div>}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export function Sheet({ open, onOpenChange, children, width = 520 }: { open: boolean; onOpenChange: (v: boolean) => void; children: ReactNode; width?: number }) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-40 bg-[#0b1220]/25" />
        <RDialog.Content style={{ width: `min(${width}px, 100vw)` }}
          className="fixed right-0 top-0 z-50 flex h-full flex-col border-l border-line bg-panel shadow-pop data-[state=open]:animate-[fade-in_.2s_ease-out]">
          <RDialog.Title className="sr-only">Details</RDialog.Title>
          {children}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export const SheetClose = RDialog.Close;

export function Menu({ trigger, items, align = "end" }: {
  trigger: ReactNode; align?: "start" | "end";
  items: ({ label: ReactNode; onSelect: () => void; danger?: boolean; icon?: ReactNode } | "sep")[];
}) {
  return (
    <RMenu.Root>
      <RMenu.Trigger asChild>{trigger}</RMenu.Trigger>
      <RMenu.Portal>
        <RMenu.Content align={align} sideOffset={6} className="z-50 min-w-[180px] rounded-md border border-line bg-panel p-1 shadow-pop animate-fade-in">
          {items.map((it, i) => it === "sep" ? <RMenu.Separator key={i} className="my-1 h-px bg-line" /> : (
            <RMenu.Item key={i} onSelect={it.onSelect}
              className={cn("flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-[13px] outline-none data-[highlighted]:bg-raised",
                it.danger ? "text-neg" : "text-fg")}>
              {it.icon}{it.label}
            </RMenu.Item>
          ))}
        </RMenu.Content>
      </RMenu.Portal>
    </RMenu.Root>
  );
}

export function Select({ value, onChange, options, placeholder, className }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: ReactNode }[]; placeholder?: string; className?: string;
}) {
  const labelId = useFieldLabel();
  return (
    <RSelect.Root value={value || undefined} onValueChange={onChange}>
      <RSelect.Trigger aria-labelledby={labelId} className={cn("inline-flex h-8 w-full min-w-0 items-center justify-between gap-2 rounded-md border border-line-strong bg-panel px-2.5 text-[13px] text-left shadow-[inset_0_1px_1px_rgb(16_24_40/0.03)] focus:outline-none focus:border-brand focus:ring-[3px] focus:ring-brand/15 data-[placeholder]:text-faint", className)}>
        <RSelect.Value placeholder={placeholder || "Selectâ€¦"} />
        <RSelect.Icon><ChevronDown className="h-3.5 w-3.5 text-muted" /></RSelect.Icon>
      </RSelect.Trigger>
      <RSelect.Portal>
        <RSelect.Content position="popper" sideOffset={4} className="z-50 max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-md border border-line bg-panel shadow-pop">
          <RSelect.Viewport className="p-1">
            {options.map((o) => (
              <RSelect.Item key={o.value} value={o.value} className="relative flex cursor-pointer select-none items-center rounded px-2 py-1.5 pl-7 text-[13px] outline-none data-[highlighted]:bg-raised">
                <RSelect.ItemIndicator className="absolute left-2"><Check className="h-3.5 w-3.5 text-brand" /></RSelect.ItemIndicator>
                <RSelect.ItemText>{o.label}</RSelect.ItemText>
              </RSelect.Item>
            ))}
          </RSelect.Viewport>
        </RSelect.Content>
      </RSelect.Portal>
    </RSelect.Root>
  );
}
