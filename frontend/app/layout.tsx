import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/lib/providers";
import { Nav } from "@/components/Nav";
import { ActiveCallOverlay } from "@/components/ActiveCallOverlay";
import { ConsultBookingPopup } from "@/components/ConsultBookingPopup";
import { OperatorNotificationPopup } from "@/components/OperatorNotificationPopup";
import { EngagementNotificationPopup } from "@/components/EngagementNotificationPopup";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Possible OS — Possible Minds",
  description: "Operating system for AI-led growth and operations",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#fafafa",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body className={`${inter.className} h-full overflow-x-hidden bg-neutral-50 text-neutral-900`}>
        <Providers>
          <div className="min-h-full pb-[calc(4.5rem_+_env(safe-area-inset-bottom))] md:pb-0 md:pl-56">
            <Nav />
            <main className="mx-auto min-w-0 max-w-[1600px] px-3 py-4 sm:px-4 md:px-8 md:py-6">
              {children}
            </main>
          </div>
          <ActiveCallOverlay />
          <OperatorNotificationPopup />
          <EngagementNotificationPopup />
          <ConsultBookingPopup />
        </Providers>
      </body>
    </html>
  );
}
