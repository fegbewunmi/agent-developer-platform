import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { getSession } from "@/lib/auth";
import { Nav } from "@/components/Nav";
import { DemoBanner } from "@/components/DemoBanner";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Orion Agent Developer Platform",
  description: "Internal control plane for registering, evaluating, and promoting AI agents",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();

  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full`}>
      <body className="min-h-full bg-bg text-text antialiased">
        {session && <Nav user={session} />}
        {session && <DemoBanner user={session} />}
        <main className="mx-auto max-w-[1400px] px-5 py-6">{children}</main>
      </body>
    </html>
  );
}
