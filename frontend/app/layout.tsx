import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/lib/providers";
import { Nav } from "@/components/Nav";
import { ActiveCallOverlay } from "@/components/ActiveCallOverlay";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Autocaller — Possible Minds",
  description: "Headless outbound BD agent",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body className={`${inter.className} h-full bg-neutral-50 text-neutral-900`}>
        <Providers>
          <div className="min-h-full pb-20 md:pb-0 md:pl-56">
            <Nav />
            <main className="mx-auto max-w-6xl px-4 py-6 md:px-8">{children}</main>
          </div>
          <ActiveCallOverlay />
        </Providers>
      </body>
    </html>
  );
}
