import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { JobProvider } from "@/context/job-context";

import "./globals.css";

export const metadata: Metadata = {
  title: "App Analyser MVP",
  description: "Local, CMDB-first enterprise application analysis",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <JobProvider>
          <AppShell>{children}</AppShell>
        </JobProvider>
      </body>
    </html>
  );
}
