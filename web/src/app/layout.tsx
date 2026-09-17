import type { Metadata } from "next";
import { Geist } from "next/font/google";
import Link from "next/link";
import { Providers } from "./providers";
import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Clinical Trial Monitoring",
  description: "Decision-support workspace for public clinical-trial records",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geist.variable} font-sans`}>
      <body>
        <nav className="border-b" aria-label="Primary navigation">
          <div className="mx-auto flex max-w-6xl gap-5 px-4 py-3 text-sm sm:px-6">
            <Link href="/changes" className="font-medium hover:underline">
              Change inbox
            </Link>
            <Link href="/" className="text-muted-foreground hover:underline">
              Study watchlist
            </Link>
          </div>
        </nav>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
