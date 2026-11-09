import type { Metadata } from "next";
import KruvimLanding from "../../components/KruvimLanding";

export const metadata: Metadata = {
  openGraph: {
    title: "Kruvim — Test your content. See how it lands.",
    description: "See how Kruvim audience testing works and create a workspace to try it.",
    type: "website",
  },
};

export default function AppLandingPage() {
  return <KruvimLanding appEntry />;
}
