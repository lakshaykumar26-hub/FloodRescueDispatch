import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Flood Rescue Dispatch — Command Dashboard",
  description: "Time-stepped, explainable flood-rescue simulation dashboard (synthetic data only).",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
