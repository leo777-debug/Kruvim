import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kruvim — Test your content before it goes live",
  description: "Test your content with simulated audiences. Explore how they react and make better-informed decisions before publishing.",
  openGraph: {
    title: "Kruvim — Test your content before it goes live",
    description: "Explore simulated audience responses. Watch the product walkthrough and request early access.",
    type: "website"
  }
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
