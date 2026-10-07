import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kruvim — Test your content. See how it lands.",
  description: "Give your video, campaign or idea a simulated test audience. Explore reactions, compare versions and find what to refine before publishing.",
  openGraph: {
    title: "Kruvim — Test your content. See how it lands.",
    description: "Explore how a simulated audience responds to your next idea. Watch the demo and join the early access list.",
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
