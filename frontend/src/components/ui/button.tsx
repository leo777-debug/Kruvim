import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-[13px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 select-none",
  {
    variants: {
      variant: {
        primary: "bg-brand text-brand-fg hover:bg-brand/90 shadow-[0_1px_1px_rgb(16_24_40/0.08)]",
        secondary: "bg-panel text-fg border border-line-strong hover:bg-raised shadow-[0_1px_1px_rgb(16_24_40/0.04)]",
        ghost: "text-muted hover:text-fg hover:bg-raised",
        outline: "border border-line-strong text-fg hover:bg-raised",
        danger: "bg-panel text-neg border border-neg/40 hover:bg-neg/5",
        link: "text-brand underline-offset-4 hover:underline px-0 h-auto",
      },
      size: { sm: "h-7 px-2.5 text-xs", md: "h-8 px-3", lg: "h-9 px-4", icon: "h-8 w-8", "icon-sm": "h-7 w-7" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, loading, children, disabled, ...props }, ref) => (
  <button ref={ref} className={cn(button({ variant, size }), className)} disabled={disabled || loading} {...props}>
    {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
    {children}
  </button>
));
Button.displayName = "Button";
