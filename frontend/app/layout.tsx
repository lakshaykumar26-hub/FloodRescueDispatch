import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Flood Rescue Dispatch | Rescue Operations",
  description: "A presentation-ready flood rescue simulation demo with live map updates.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
